# POC NetScaler piloté par Crossplane — dossier de spikes

Version : 0.1 — 6 octobre 2026. Statut : protocole préparé, tests non exécutés.

## 1. Décision à éclairer

Peut-on proposer un produit LoadBalancer piloté par Crossplane, en réutilisant le provider Terraform `citrix/citrixadc` via une MR `Workspace`, avec un cycle de vie fiable sur un ADC partagé ?

Le succès attendu dépasse la création d'un objet : création, modification, stabilité, reprise, adoption, suppression et trafic doivent être démontrés. Un contournement documenté n'est accepté qu'après un test montrant son efficacité et son coût opérationnel.

## 2. Parcours et périmètre

Parcours principal : consommateur → XR → Composition → MR Workspace → provider Crossplane OpenTofu → module HCL → provider Terraform citrixadc → NITRO → CPX.

La XRD définit le contrat de la XR. Le backend conserve le state ; Git fournit le module. Deux providers distincts interviennent. Un Workspace est une MR Crossplane, pas seulement un workspace CLI Terraform.

Choix proposés, à confirmer par les spikes :

| Élément | Choix initial | Motif / réserve |
|---|---|---|
| Cible ADC | CPX Express en Docker | Lab local économique ; différences réseau à qualifier |
| Contrôle | kind + Crossplane | Cluster dédié au POC pour éviter de perturber un autre lab |
| Moteur | provider-opentofu | Qualifier la release et son installation sur Crossplane retenu |
| Provider ADC | citrix/citrixadc épinglé | Pas de version flottante |
| Backend | Kubernetes pour les premiers tests | State et Lease hors du pod ; survie au reset kind non garantie |
| Granularité | Un Workspace par LB logique | Vserver, pool et bindings gérés ensemble |
| Trafic | HTTP + deux backends identifiables | Vérifier le résultat au-delà du statut Kubernetes |
| TLS | Étape après HTTP | Éviter de mélanger les causes d'échec initiales |
| Upjet | Piste optionnelle | Aucun provider à générer dans le parcours principal |

CPX ne prouve pas la HA VPX/MPX, les VLAN, le routage d'entreprise, les VIP flottantes ou les performances de production. AWS et l'IPAM restent une phase ultérieure.

## 3. Faits documentés et hypothèses à tester

| Sujet | Point de départ | Source |
|---|---|---|
| Workspace | HCL inline ou distant, variables et Secrets possibles ; outputs exposables | S1 |
| Runtime | Polling annoncé à 10 minutes, timeout annoncé à 20 minutes ; vérifier les réglages de la release | S1 |
| State | Le provider n'assure pas seul sa persistance | S1 |
| Backend Kubernetes | State dans Secret, verrou dans Lease, taille maximale du Secret : 1 MiB | S2 |
| CPX | Express gratuit, NITRO disponible ; compatibilité des ressources choisies à tester | S3, S4 |
| ADC | README citrixadc : sauvegarde persistante non automatique ; limitation signalée pour l'attribut `state` du lbvserver | S5 |
| Upjet | Configuration d'identité, références, champs sensibles et late initialization requiert une qualification | S7 |

Les limites du README peuvent dépendre de la release et de la ressource : mesurer le comportement effectif avant de conclure.

## 4. Convention de preuve

Chaque spike produit un résultat : PASS, PASS AVEC RÉSERVE, FAIL ou NON EXÉCUTÉ. Tous sont NON EXÉCUTÉS à la création de ce document.

À conserver pour chaque cas : versions et digests ; commit du module ; contexte et namespace ; commandes sans secrets ; horodatages ; conditions XR/Workspace ; plan expurgé ; inventaire ADC avant/après ; résultats HTTP ; identités du state et des objets ; décision et limite résiduelle.

Ne pas déposer un state brut, des credentials, des clés ou un plan contenant des secrets dans Git. Les preuves utilisent des noms de lab préfixés `poc-` et un périmètre explicitement isolé.

Seuils proposés pour rendre la décision mesurable, pas garanties des produits :

- Trois cycles de polling sans changement après stabilisation.
- Reprise et réparation dans deux intervalles de polling + durée maximale d'un apply mesurée.
- Zéro doublon, zéro changement d'un autre LB, zéro recréation inexpliquée.
- Vingt requêtes HTTP réussies pour le test fonctionnel, avec les deux backends observés sur connexions distinctes et sans persistance de session.
- Suppression terminée en moins de cinq minutes en conditions nominales de lab ; un délai dépassé exige une explication et une décision.

## 5. Ordre des spikes et décisions intermédiaires

| ID | Question principale | Dépendance | Porte de décision |
|---|---|---|---|
| NS-001 | Le lab CPX et NITRO sont-ils utilisables ? | Aucune | Accès à la cible |
| NS-002 | Le module HCL est-il compatible et stable ? | 001 | CRUD direct fiable |
| NS-003 | State et identités survivent-ils à une reprise ? | 002 | Pas de doublon à la reprise |
| NS-004 | Le Workspace pilote-t-il le module correctement ? | 003 | Accostage Crossplane validé |
| NS-005 | Les bindings et deux LB restent-ils isolés ? | 004 | ADC partagé envisageable |
| NS-006 | La dérive est-elle détectée et corrigée ? | 005 | Limites par attribut connues |
| NS-007 | La configuration ADC persiste-t-elle ? | 004 | Persistance qualifiée |
| NS-008 | Les pannes et locks ont-ils une reprise maîtrisée ? | 003–007 | Procédure de récupération |
| NS-009 | Peut-on adopter un LB existant ? | 005 | Accostage brownfield |
| NS-010 | La suppression respecte-t-elle le périmètre ? | 005, 007, 008 | Cycle de vie complet |
| NS-011 | Secrets et droits sont-ils maîtrisés ? | 004 | Conditions d'exploitation |
| NS-012 | L'API produit expose-t-elle un statut utile ? | 004–011 | XR LoadBalancer démontrée |
| NS-013 | Versions, charge et passage VPX sont-ils maîtrisés ? | 012 | Suite du POC |
| NS-U01 | Un provider Upjet apporterait-il une valeur suffisante ? | Optionnel | Choix d'architecture alternatif |

Commencer par HCL direct ; introduire le Workspace ensuite ; ajouter la XRD une fois le cycle de vie qualifié. Cela facilite l'attribution des erreurs à la bonne couche.

## 6. Fiches détaillées

### NS-001 — Lab CPX, accès et réseau

**Questions.** L'image retenue démarre-t-elle sur le poste ? Le contrôleur dans kind peut-il joindre NITRO ? Comment un client joint-il le virtual server dans le réseau Docker ?

**Protocole.** Relever image/digest et prérequis officiels. Démarrer CPX et deux backends A/B. Tester NITRO depuis l'hôte puis depuis un pod. Définir une table explicite des endpoints hôte/pod, ports publiés et adresses CPX/backends. Utiliser les credentials réellement configurés sur l'image, pas supposer un mot de passe par défaut.

**Validation.** API joignable depuis l'exécuteur et backends joignables depuis CPX ; procédure reproductible ; Express identifié.

**Limites.** `localhost` dans le pod n'est pas le poste. Les VIP CPX ne reproduisent pas librement les VIP d'une appliance.

**Contournements à tester.** Réseau Docker partagé entre CPX/backends et nœuds kind, ou publication explicite des ports. Désigner un endpoint stable. Ne pas installer un ingress controller qui gérerait aussi les mêmes objets.

### NS-002 — HCL direct, schémas et idempotence

**Questions.** Les ressources lbvserver, servicegroup, membres et binding sont-elles supportées ? Quels champs sont requis, exclusifs, ignorés ou provoquent un remplacement ?

**Protocole.** Sur un LB jetable : fmt/validate, plan, apply, vingt requêtes, second plan. Changer successivement méthode de répartition, membre puis port. Documenter pour chaque attribut le résultat du plan et le comportement du trafic. Lire le schéma de la version épinglée, identifier les champs nécessitant suppression/recréation et les valeurs normalisées par CPX.

**Validation.** Plan sans changement après stabilisation ; modifications attendues ; pas de double gestion des bindings via bloc inline et ressource dédiée.

**Limites.** Les garanties du schéma ne suffisent pas à prouver le comportement de NITRO.

**Contournements.** Réduire le contrat produit aux attributs qualifiés, séparer les bindings, épingler une release corrigée. `ignore_changes` est un dernier recours : il abandonne la réconciliation du champ et doit être déclaré comme limite.

### NS-003 — Identité, backend et survie au redémarrage

**Questions.** Comment external-name du Workspace, clé/suffixe de backend, workspace CLI et IDs ADC se combinent-ils ? Que survit-il à la perte du répertoire d'exécution ?

**Protocole.** Fixer l'identité logique A. Relever l'adresse HCL, l'ID ADC et l'identifiant du state. Réexécuter depuis un répertoire vide utilisant le même backend. Puis redémarrer le pod provider une fois NS-004 disponible. Créer B et prouver que son state diffère. Tester la restauration d'une sauvegarde sur un périmètre jetable, sans writer actif.

**Validation.** Mêmes IDs, aucun doublon, aucune création inattendue ; droits Secret/Lease suffisants ; isolation A/B.

**Limites.** Backend Kubernetes dans kind survit au pod, pas nécessairement à la suppression du cluster. Changer le nom du Workspace peut changer le state sélectionné ; ne pas le faire comme un simple renommage.

**Contournements.** Identité stable définie avant création ; backend externe sauvegardé pour reset cluster ; migration explicite de state. Aucune réparation par ré-apply à l'aveugle après perte du state.

### NS-004 — Accostage par MR Workspace

**Questions.** Le package choisi fonctionne-t-il avec le Crossplane du POC ? Quels scopes, ProviderConfig, champs et politiques sont réellement supportés ?

**Protocole.** Installer une release épinglée ; inspecter les CRD installées et la documentation de cette release. Créer un Workspace utilisant le module validé, un backend isolé et des références de Secrets. Observer conditions, outputs et logs expurgés. Modifier une variable, mesurer le délai ; redémarrer le contrôleur.

**Validation.** Workspace convergent, modification effective, outputs exploitables, reprise sans mutation imprévue.

**Limites.** Ready du Workspace ne prouve pas que le service HTTP répond. L'unité de contrôle reste le module entier. Ne pas supposer que toutes les managementPolicies Crossplane sont implémentées.

**Contournements.** Ajuster version/runtime, fractionner un module trop large, ajouter une sonde fonctionnelle. Arrêter cette piste si les opérations indispensables ne sont pas supportées.

### NS-005 — Bindings, ordre et isolation sur ADC partagé

**Questions.** Le graphe HCL crée/supprime-t-il les dépendances correctement ? Deux modules peuvent-ils gérer des objets distincts sans écraser une collection partagée ?

**Protocole.** Deux LB A/B, noms et states distincts. Ajouter/retirer un membre de A puis comparer B et l'inventaire global. Démarrer avec concurrence contrôleur à 1 et parallélisme HCL réduit si configurable. Ensuite deux opérations simultanées sur objets distincts. Interdire toute définition du même objet dans deux states.

**Validation.** Aucun objet B modifié ; pas d'update loop ; suppression d'un binding sans effet sur les autres.

**Limites.** Un lock de state A ne protège pas le state B ; il ne sérialise pas globalement les opérations sur l'ADC.

**Contournements.** Propriété explicite des objets/collections, ressources de binding dédiées, sérialisation temporaire. Une file par ADC ou un verrou global exige une conception supplémentaire ; ne pas supposer qu'elle existe dans le provider.

### NS-006 — Dérive, normalisation et boucles

**Questions.** Quels attributs sont lus et corrigés ? Que se passe-t-il après désactivation manuelle d'un vserver ?

**Protocole.** Modifier via NITRO la méthode LB, un binding et l'état activé/désactivé, chacun séparément. Mesurer détection/réparation. Observer trois polls à vide. Comparer HCL, réponses API et plan pour valeurs par défaut, champs exclusifs, listes et ordre des membres.

**Validation.** Matrice par champ : détecté, corrigé, ignoré ou non supporté ; aucun write répété au repos.

**Limites.** Le README signale une limite sur `state` : la tester, ne pas promettre sa réparation. La late initialization Upjet ne s'applique pas à cette route Workspace.

**Contournements.** Normaliser les entrées ; exclure un champ du contrat ; correctif upstream. Action NITRO dédiée possible pour `state`, mais avec un seul propriétaire défini et sans deuxième boucle concurrente.

### NS-007 — Sauvegarde et persistance ADC

**Questions.** Quelles mutations sont sauvegardées ? Quelle différence entre redémarrer le conteneur et recréer CPX sans son stockage ?

**Protocole.** Comparer, sur cible jetable, création sans sauvegarde et avec sauvegarde explicite. Contrôler séparément restart avec stockage conservé, puis recréation avec stockage conservé et sans stockage. Répéter après update et delete. Lors d'un crash, observer l'inventaire avant de relancer le contrôleur pour distinguer persistance native et reconstruction par réconciliation.

**Validation.** Matrice mutation/sauvegarde/redémarrage ; aucune résurrection d'un objet supprimé après restauration du stockage.

**Limites.** Le README demande une action de commit distincte. Une sauvegarde globale peut aussi persister les modifications d'autres acteurs ; ce n'est pas une transaction par Workspace.

**Contournements.** Hook testé après mutations réussies ou mécanisme coordonné par ADC. Un provisioner déclenché uniquement à la création ne couvre pas les updates/deletes. Les mécanismes exacts de persistance CPX doivent suivre la version retenue.

### NS-008 — Échec partiel, timeout et verrou

**Questions.** Une panne entre deux créations laisse-t-elle des objets non suivis ? Le retry reprend-il ? Quand peut-on retirer un lock ?

**Protocole.** Cas jetables : NITRO inaccessible avant apply ; coupure après création du vserver avant binding ; indisponibilité backend ; interruption du pod en cours d'apply ; dépassement contrôlé du timeout. Vérifier state, Lease et inventaire avant retry. Tester une récupération avec erreur d'authentification puis credentials restaurés.

**Validation.** Erreur compréhensible, retry borné, absence de doublon, objets partiels réconciliés ou procédure d'import/nettoyage documentée.

**Limites.** Les appels NITRO ne sont pas une transaction HCL globale ; un verrou persistant peut être légitime.

**Contournements.** Ajuster timeout client et runtime à la durée mesurée ; réduire parallélisme ; import ciblé. `force-unlock` uniquement après preuve qu'aucun writer ne travaille et sauvegarde du state ; jamais automatique à chaque erreur.

### NS-009 — Adoption brownfield et transfert de responsabilité

**Questions.** Un LB manuel ou issu d'un pipeline existant peut-il être repris sans remplacement ? Quels IDs d'import utilisent les bindings ?

**Protocole.** Créer hors du nouveau module un LB A complet. Faire l'inventaire et sauvegarder. Arrêter l'ancien writer. Aligner le HCL et importer tous les objets dans le backend destiné au Workspace, avec le même workspace CLI effectivement utilisé. Plan sans mutation ; démarrer ensuite le Workspace et modifier un attribut non disruptif.

**Validation.** Même identité et trafic conservé ; plan initial sans delete/replace ; un seul writer.

**Limites.** L'external-name de la MR Workspace n'importe pas automatiquement chacun des objets ADC contenus dans le module. Observe-only, s'il est supporté, n'est pas une procédure d'import du state.

**Contournements.** Import avec le CLI ou blocs d'import selon moteur/version qualifiés. Pour un state existant : migration ou transfert d'entrées explicitement préparé. Rollback de responsabilité vers l'ancien writer seulement après neutralisation du nouveau.

### NS-010 — Suppression, finalizers et objets partagés

**Questions.** Que détruit la suppression du Workspace ? Que préserve une politique de conservation effectivement supportée ?

**Protocole.** Supprimer A pendant que B existe. Vérifier ordre bindings/pool/vserver, absence d'objets orphelins et B intact. Refaire avec API ADC indisponible puis restaurée. Tester la politique de conservation disponible dans la release. Après NS-012, répéter par suppression de la XR.

**Validation.** Suppression complète ou conservation explicite ; finalizer libéré après nettoyage confirmé ; B intact ; delete persisté selon NS-007.

**Limites.** Un objet partagé ne doit pas être propriété destructive de deux modules. Retirer un finalizer manuellement ne nettoie pas l'ADC.

**Contournements.** Sortir les ressources partagées du module LB ; référencer l'existant ; restaurer connectivité/credentials pour terminer la suppression. Prévoir une procédure de nettoyage contrôlé plutôt qu'une suppression forcée systématique.

### NS-011 — Secrets, TLS et droits minimaux

**Questions.** Où apparaissent credentials et données sensibles ? Une rotation de Secret provoque-t-elle une nouvelle utilisation ? Quels privilèges NITRO/backend sont indispensables ?

**Protocole.** Injecter credentials via Secret. Auditer logs, statut, outputs, erreurs et copies d'exécution sans publier leur contenu sensible. Tester mauvais credentials, rotation, CA non reconnue puis reconnue. Refaire CRUD avec un compte restreint et RBAC backend minimal ; retirer une permission et vérifier l'erreur.

**Validation.** Pas de secret dans Git ni statut/outputs publics ; TLS vérifié pour la cible d'exploitation ; droits documentés ; rotation effective sans perte du state.

**Limites.** Sensitive masque certains affichages mais ne chiffre pas automatiquement le state. Le comportement de rotation dépend du provider et du polling.

**Contournements.** CA montée/configurée, politique explicite de redémarrage si rotation non observée, réduction des outputs. Dérogation HTTP locale uniquement si CPX impose ce mode dans le montage testé, documentée et non reconduite comme choix de production.

### NS-012 — XRD, Composition et statut produit

**Questions.** Une XR suffit-elle à consommer le LB ? Les erreurs du Workspace et la santé du trafic sont-elles distinguées ?

**Protocole.** Définir une API minimale : cible ADC logique, protocole, port, backends, algorithme et paramètres VIP compatibles CPX. Endpoint d'administration et credentials fournis par la plateforme. Générer un Workspace déterministe et une clé de state stable. Renvoyer VIP/endpoint, version du module et état de provisioning. Tester input invalide, backend indisponible, modification et suppression de XR. Contrôler les scopes réels des CRD avant les références inter-namespace.

**Validation.** Contrat clair ; résolution stable ; pas de remplacement du Workspace lors d'un simple update ; statut provisionné distinct de service fonctionnel.

**Limites.** La validation du schéma d'une XR ne vérifie pas toutes les règles ADC. Un Workspace Synced/Ready ne garantit pas disponibilité du LB.

**Contournements.** Validations OpenAPI/CEL ou admission adaptées ; sonde externe pour santé fonctionnelle ; message d'erreur synthétique, lien vers détail technique. Ne pas imposer Upjet pour conserver Patch & Transform : celui-ci peut composer le Workspace.

### NS-013 — Versions, charge et qualification VPX

**Questions.** Une nouvelle release modifie-t-elle le schéma ou le plan ? Quel volume supporte le contrôleur ? Quelles preuves manquent sur VPX ?

**Protocole.** Épingler image CPX, package provider, moteur embarqué, provider ADC, fonctions et commit module. Tester upgrade sur copie jetable, puis rollback du code avec plan inspecté. Monter de 1 à 2 puis 10 LB si les premiers tests passent ; mesurer durée, CPU/mémoire, erreurs API et polling. Répéter les cas critiques sur la version cible VPX, avec allocation IP et réseau réels.

**Validation.** Matrice de compatibilité enregistrée ; aucune upgrade silencieuse ; charge mesurée ; réserves CPX explicites.

**Limites.** Dix LB ne prouvent pas l'échelle de production. Le state après upgrade n'est pas nécessairement compatible avec un downgrade du provider.

**Contournements.** Versions immuables, sauvegarde avant évolution, rollout progressif, budget de concurrence par ADC. Sur AWS, qualifier aussi ENI/adresses secondaires et accès réseau ; ne pas attribuer leur gestion au provider citrixadc sans validation.

### NS-U01 — Branche optionnelle Upjet

**Question.** Les MR par objet sont-elles nécessaires pour justifier la maintenance d'un provider généré ?

**Protocole.** Seulement si décidé après le parcours Workspace : générer un vserver et un binding ; qualifier mode SDK/Framework/CLI compatible avec la version Citrix ; adapter external-name et ID composite ; références ; champs Sensitive ; exclusions de late initialization ; scope namespaced/cluster ; import, reprise et deletion.

**Validation.** CRUD et adoption sans boucle ; évolution CRD maîtrisée ; valeur mesurable par rapport au Workspace.

**Limites.** La génération ne corrige pas la logique du provider TF et ne règle pas automatiquement commit ADC ou conflits entre writers.

**Contournements.** Configurateurs Upjet, correctif provider upstream ou provider natif pour un besoin de réconciliation plus spécifique. Conserver le module Workspace si le bénéfice ne compense pas l'effort.

## 7. Première session : NS-001 puis NS-002

Préflight non destructif sur le poste cible :

```bash
docker version
docker info
kubectl version --client
kind version
helm version --short
tofu version
kubectl config current-context
```

Ces commandes ne constituent pas une installation. Un cluster dédié et les versions retenues seront renseignés avant les commandes de création. Aucun reset du cluster existant n'est demandé.

Ordre pratique :

1. Sélectionner l'image CPX et lire ses prérequis de capabilities, stockage et credentials ; relever le digest.
2. Démarrer un CPX et deux backends portant chacun une réponse identifiable.
3. Prouver NITRO depuis l'hôte et depuis un pod ; écrire la table réseau.
4. Écrire le module HTTP minimal d'après le schéma du provider épinglé.
5. Faire fmt/validate et un plan sur cible jetable ; inspecter avant apply.
6. Vérifier les objets via NITRO puis le trafic ; obtenir un second plan sans changement.
7. Passer au backend durable avant d'exécuter ce même module via Workspace.

Exemples de vérifications HCL à exécuter dans le répertoire du module :

```bash
tofu fmt -check
tofu init
tofu validate
tofu providers schema -json > provider-schema.json
tofu plan -detailed-exitcode
```

`plan -detailed-exitcode` : 0 = aucun changement, 1 = erreur, 2 = changements. Après stabilité, le résultat attendu est 0. Adapter l'authentification du backend et la sélection du workspace CLI au protocole NS-003 ; ne pas passer les secrets en arguments de commande.

## 8. Gabarit de compte rendu

À reproduire pour chaque spike :

| Champ | Valeur à renseigner |
|---|---|
| ID / date / exécutant | |
| Versions / commit / digests | |
| Hypothèse et cas exécutés | |
| Résultat | NON EXÉCUTÉ / PASS / PASS AVEC RÉSERVE / FAIL |
| Preuves expurgées | |
| Comportement réel vs attendu | |
| Limite observée | |
| Workaround testé et résultat | |
| Coût opérationnel du workaround | |
| Décision et prochaine action | |

La décision finale indique : périmètre qualifié, champs réconciliables, politique de state/locks, persistance, suppression, responsabilités et conditions de qualification VPX. Une limite critique sur identité, isolation ou reprise bloque le passage au produit consommable.

## 9. Documentation officielle

Sources consultées le 6 octobre 2026. Les procédures doivent être recoupées avec les versions effectivement épinglées.

- S1 — [Provider Crossplane OpenTofu](https://github.com/upbound/provider-opentofu).
- S2 — [Backend OpenTofu Kubernetes](https://opentofu.org/docs/language/settings/backends/kubernetes/).
- S3 — [Licences CPX / Express](https://docs.netscaler.com/us/en/cpx/current-release/cpx-licensing.html).
- S4 — [Configuration CPX et API NITRO](https://docs.netscaler.com/us/en/cpx/current-release/configure-cpx.html).
- S5 — [Provider Terraform Citrix ADC : configuration, limites, commit](https://github.com/citrix/terraform-provider-citrixadc).
- S6 — [Crossplane Managed Resources](https://docs.crossplane.io/latest/managed-resources/managed-resources/).
- S7 — [Upjet : configuration des ressources](https://github.com/crossplane/upjet/blob/main/docs/configuring-a-resource.md).
- S8 — [Ressource lbvserver](https://github.com/citrix/terraform-provider-citrixadc/blob/master/docs/resources/lbvserver.md).
- S9 — [Déploiement VPX standalone sur AWS](https://docs.netscaler.com/us/en/vpx/current-release/deploy-aws/launch-vpx-for-aws-ami.html).

Les protocoles, seuils et workarounds de ce dossier sont des propositions d'ingénierie à éprouver ; ils ne sont pas des garanties annoncées par les éditeurs.
