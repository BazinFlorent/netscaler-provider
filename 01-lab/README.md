# Lab NetScaler — procédure de rejeu

État au 9 octobre 2026 : NS001 et NS002 terminés ; NS003 validé pour le volet CLI ; NS004 validé pour le cycle de vie nominal par MR Workspace et la reprise opérationnelle du provider. Les LB des spikes terminés sont supprimés ; CPX et les backends sont conservés. L’actualisation des IP par script est validée ; un rejeu NS004 après nettoyage a recréé un LB fonctionnel le même jour. Le LB NS004 est désormais actif pour cette nouvelle session.

Ce fichier est destiné à **`01-lab/README.md`**. Il donne les commandes opérationnelles de rejeu à partir du dépôt ; les [CR des spikes](../00-docs/spikes/) conservent les questions, observations et limites. La commande initiale de bootstrap du cluster reste extérieure à ce guide.

## Prérequis

- WSL Linux, Docker Engine accessible et plugin Docker Compose.
- Cluster kind `netscaler-provider` déjà bootstrappé, contexte `kind-netscaler-provider`, réseau Docker `kind`.
- kubectl, kind, Helm, curl, jq et OpenTofu (version qualifiée : 1.13.1).
- Fichiers du dépôt présents : [Compose](cpx/compose.yaml), [launch.sh](cpx/launch.sh) et module `hcl/netscaler/{versions,provider,variables,main}.tf`.
- `.local/` et les répertoires `.terraform/` ignorés par Git ; `.terraform.lock.hcl` conservé dans Git.
- Accès aux registries pour les images et le provider manquants.

Versions qualifiées : CPX 14.1-73.30, Compose 5.6.0, Crossplane 2.4.0 et citrixadc 2.3.0. Les digests du lab sont dans [NS-001](../00-docs/spikes/NS-001.md) ; les fichiers HCL complets et leur rôle sont dans [NS-002](../00-docs/spikes/NS-002.md).

Exécuter les commandes depuis la **racine du dépôt**, dans un même terminal pour conserver les variables exportées. Ce guide suppose que le state du module est conservé si le LB existe déjà. Un checkout du code seul ne restaure pas le state local ni la propriété des objets ADC existants.

## 1. Démarrer le lab

```bash
docker compose -f 01-lab/cpx/compose.yaml config --quiet
./01-lab/cpx/launch.sh
```

Le script valide le modèle Compose, démarre les services, affiche leur statut puis appelle les backends avec des retries. Il ne remplace pas les tests NITRO ni l’ensemble de NS-001. Si le démarrage prend du temps, relancer les vérifications après disponibilité :

```bash
docker compose -f 01-lab/cpx/compose.yaml ps
docker compose -f 01-lab/cpx/compose.yaml logs --tail=80 cpx
curl -fsS http://127.0.0.1:18081/
curl -fsS http://127.0.0.1:18082/
```

Attendu : trois conteneurs Up, CPX démarré et réponses `backend-a`, `backend-b`. `config --quiet` vérifie le modèle Compose, pas la disponibilité des services.

## 1.1. Reprendre NS-004 après un arrêt du lab

Les adresses du réseau Docker `kind` sont dynamiques : elles peuvent changer lors d’un arrêt/redémarrage, et ne sont pas garanties au rejeu. `launch.sh` démarre les services mais ne met pas à jour le manifeste du MR Workspace. Les variables shell utilisées pour générer ce manifeste sont remplacées une seule fois ; Kubernetes conserve ensuite des valeurs fixes.

Incident observé le 9 octobre 2026 : CPX et les deux backends étaient arrêtés. Le Workspace affichait `SYNCED=False`, `READY=True`, avec `no route to host` vers l’ancienne IP NITRO. Après le lancement du lab, les IP avaient changé :

| Conteneur | Ancienne IP | IP après reprise |
|---|---|---|
| CPX | 172.18.0.7 | 172.18.0.6 |
| Backend A | 172.18.0.8 | 172.18.0.7 |
| Backend B | 172.18.0.6 | 172.18.0.8 |

Ces valeurs documentent cette session ; toujours récupérer les IP effectives :

```bash
docker compose -f 01-lab/cpx/compose.yaml ps
docker inspect \
  poc-netscaler-cpx \
  poc-netscaler-backend-a \
  poc-netscaler-backend-b \
  --format '{{.Name}} => {{with index .NetworkSettings.Networks "kind"}}{{.IPAddress}}{{end}}'
```

Après démarrage de CPX, mettre à jour `01-lab/crossplane/ns004/workspace.yaml` :

- `spec.forProvider.env` : entrée `NS_URL` = `http://<IP actuelle CPX>:9080` ; ce chemin est utilisé depuis le pod du provider.
- `spec.forProvider.varmap.vip` : IP actuelle CPX.
- `spec.forProvider.varmap.backends` : IP actuelle de chaque membre déclaré, port 8080.

Conserver le choix des membres du scénario en cours. Si A a été retiré, ne garder que B ; ne pas recréer automatiquement A/B pour résoudre un incident réseau. Les ports publiés sur la WSL restent `18080` pour le LB sur 8080, `18081` pour A, `18082` pour B et `19080` pour NITRO.

Rafraîchir le Secret avec le mot de passe initial actuel du lab (si le mot de passe a été changé manuellement, utiliser celui en vigueur) :

```bash
CPX_PASSWORD="$(docker exec poc-netscaler-cpx \
  cat /var/deviceinfo/random_id)"

printf '%s' "$CPX_PASSWORD" \
  | kubectl --context kind-netscaler-provider \
      create secret generic ns004-nitro \
      -n netscaler-ns004 \
      --from-file=NS_PASSWORD=/dev/stdin \
      --dry-run=client -o yaml \
  | kubectl --context kind-netscaler-provider apply -f -

kubectl --context kind-netscaler-provider apply \
  -f 01-lab/crossplane/ns004/workspace.yaml

kubectl --context kind-netscaler-provider get \
  workspaces.opentofu.m.upbound.io ns004-http \
  -n netscaler-ns004 -o json | jq '.status.conditions'
```

Attendu : `Synced=True`, `Ready=True` après réconciliation. `READY=True` seul ne valide pas l’état courant ; lire le message de `Synced` en cas d’erreur. Vérifier ensuite le LB et le trafic :

```bash
docker exec poc-netscaler-cpx \
  /var/netscaler/bins/cli_script.sh "show lb vserver poc-ns004-http"

for request in $(seq 1 10); do
  printf '%02d : ' "$request"
  curl -fsS --connect-timeout 5 --max-time 10 \
    http://127.0.0.1:18080/ || break
done
curl -fsS --connect-timeout 5 --max-time 10 http://127.0.0.1:18081/
```

Résultat confirmé dans cette session avec B seul déclaré : LB UP avec un membre B, dix réponses `backend-b` via le LB et `backend-a` en accès direct. La modification de membres et la remise en état après changement d’IP ont été combinées ; ce résultat ne qualifie pas un retrait isolé sans changement réseau.

L’actualisation est désormais réalisée par `crossplane/ns004/refresh-ips.py`, décrit en section 1.2. Le manifeste lui-même ne fait pas de découverte dynamique : il doit être actualisé avant un apply explicite. Ne pas remplacer les IP par les noms Compose sans valider leur résolution depuis les pods Kubernetes et la prise en charge des noms par les ressources CitrixADC concernées.

## 1.2. Actualiser automatiquement les IP du Workspace NS004 — VALIDÉ

Script versionné : [refresh-ips.py](crossplane/ns004/refresh-ips.py), à côté de workspace.yaml. Il récupère les adresses IPv4 Docker sur le réseau kind et actualise uniquement :

- l’entrée NS_URL dans spec.forProvider.env, vers CPX:9080 ;
- spec.forProvider.varmap.vip, avec l’IP CPX ;
- les champs ip des membres a/b **déjà déclarés** dans varmap.backends.

Le script conserve le HCL, les commentaires, les ports, la méthode et le choix des membres. Il ne rétablit pas un membre retiré. Il vérifie que CPX et les backends déclarés tournent avec des IP attribuées ; en cas d’échec, il ne remplace pas le manifeste. Il n’exécute ni kubectl apply ni mise à jour du Secret NITRO.

Dépendance : Python 3 et PyYAML. Dans la WSL Arch Linux :

```bash
python3 -c 'import yaml'
# Si le module manque :
# sudo pacman -S python-yaml
```

Séquence habituelle, depuis la racine du dépôt :

```bash
./01-lab/cpx/launch.sh
python3 01-lab/crossplane/ns004/refresh-ips.py --dry-run
python3 01-lab/crossplane/ns004/refresh-ips.py
git diff -- 01-lab/crossplane/ns004/workspace.yaml
```

Le script cherche par défaut workspace.yaml à côté de lui : il fonctionne aussi depuis un autre répertoire si l’on fournit le chemin du script. Options : --file pour un autre manifeste, --network pour un autre réseau, --dry-run pour simuler sans écrire. Un contenu YAML non compatible ou un membre inconnu provoque une erreur ; les seuls membres connus sont a et b.

Résultat acquis dans le lab réel : `IP déjà à jour ; fichier inchangé.` Pour démontrer une correction, le test a volontairement modifié l’endpoint et la VIP dans une copie temporaire :

```bash
cp 01-lab/crossplane/ns004/workspace.yaml /tmp/ns004-ip-check.yaml
# Valeur historique du test : adapter si l’IP actuelle CPX diffère.
sed -i 's/172\.18\.0\.6/192.0.2.123/g' /tmp/ns004-ip-check.yaml
python3 01-lab/crossplane/ns004/refresh-ips.py \
  --file /tmp/ns004-ip-check.yaml
diff -u 01-lab/crossplane/ns004/workspace.yaml /tmp/ns004-ip-check.yaml
```

Résultat partagé : NS_URL corrigé de http://192.0.2.123:9080 vers http://172.18.0.6:9080 ; vip corrigée vers 172.18.0.6 ; diff sans sortie. Le manifeste réel n’a pas été modifié par ce test. Les comportements B seul préservé, conteneur arrêté bloquant l’écriture et conservation du HCL/commentaires ont été vérifiés par simulation pendant la préparation du script ; ces cas n’ont pas tous été rejoués dans la WSL.

Après examen du diff, si le déploiement est souhaité :

```bash
kubectl --context kind-netscaler-provider apply \
  -f 01-lab/crossplane/ns004/workspace.yaml
```

Si le MR a été supprimé, cet apply **recrée le LB**. Si le mot de passe a changé, rafraîchir le Secret par la section 1.1 ou 12 avant déploiement. Le script ne vérifie pas la disponibilité de NITRO ; attendre ensuite la génération et les conditions selon la section 13, puis tester l’ADC et le trafic.

### Rejeu complet confirmé après nettoyage

Le 9 octobre 2026, après suppression nominale du MR, la séquence launch.sh → refresh-ips.py → apply a été exécutée : trois conteneurs Running, réponses directes backend-a/backend-b, IP déjà correctes, MR `created`.

Contrôles exécutés :

```bash
kubectl --context kind-netscaler-provider get \
  workspaces.opentofu.m.upbound.io ns004-http \
  -n netscaler-ns004 -o json | jq '{
    generation: .metadata.generation,
    conditions: .status.conditions
  }'
docker exec poc-netscaler-cpx \
  /var/netscaler/bins/cli_script.sh "show lb vserver poc-ns004-http"
for request in $(seq 1 20); do
  printf '%02d : ' "$request"
  curl -fsS --connect-timeout 5 --max-time 10 \
    http://127.0.0.1:18080/ || break
done
```

Résultats : nouvelle génération 1, Synced True/ReconcileSuccess avec observedGeneration 1, Ready True ; virtual server UP sur 172.18.0.6:8080, méthode ROUNDROBIN, deux membres actifs (A 172.18.0.7, B 172.18.0.8). Vingt réponses alternées B/A, soit dix de chaque backend. Le LB reste actif après ce rejeu. L’identité de son nouveau state n’a pas été relevée ; ne pas réutiliser la lineage de la session précédente comme preuve de ce nouveau cycle.

## 2. Configurer la session HCL

Les IP Docker sont calculées à chaque session, sans recopier les IP historiques. Aucun mot de passe n’est inscrit dans les fichiers HCL.

```bash
export NS_URL="http://localhost:19080/"
export NS_LOGIN="nsroot"
export NS_PASSWORD="$(docker exec poc-netscaler-cpx \
  cat /var/deviceinfo/random_id)"

export TF_VAR_vip="$(docker inspect poc-netscaler-cpx \
  --format '{{with index .NetworkSettings.Networks "kind"}}{{.IPAddress}}{{end}}')"

BACKEND_A_IP="$(docker inspect poc-netscaler-backend-a \
  --format '{{with index .NetworkSettings.Networks "kind"}}{{.IPAddress}}{{end}}')"
BACKEND_B_IP="$(docker inspect poc-netscaler-backend-b \
  --format '{{with index .NetworkSettings.Networks "kind"}}{{.IPAddress}}{{end}}')"

export TF_VAR_backends="$(jq -cn \
  --arg a "$BACKEND_A_IP" --arg b "$BACKEND_B_IP" \
  '{a: {ip: $a, port: 8080}, b: {ip: $b, port: 8080}}')"

export TF_VAR_lb_port=8080
```

Choisir explicitement la méthode selon le point de reprise :

```bash
# Reprendre l’état actuel après les tests déjà réalisés
export TF_VAR_lb_method="LEASTCONNECTION"

# Pour rejouer depuis la configuration initiale, utiliser à la place :
# export TF_VAR_lb_method="ROUNDROBIN"
```

ROUNDROBIN est le défaut du HCL, mais LEASTCONNECTION est la configuration de l’ADC à la pause documentaire. Ne pas interpréter un plan proposant le retour à ROUNDROBIN comme une dérive si cet override a simplement changé.

Tester NITRO :

```bash
curl -sS --max-time 10 \
  -H 'X-NITRO-USER: nsroot' -H "X-NITRO-PASS: $NS_PASSWORD" \
  "${NS_URL}nitro/v1/config/nsversion" | jq
```

Attendu : `errorcode: 0`, build 73.30.nc. `random_id` contient le mot de passe initial généré ; si les credentials ont été modifiés, utiliser la valeur active. Ne pas activer `set -x` ou afficher NS_PASSWORD.

## 3. Initialiser le backend local et valider le module

```bash
mkdir -p .local/ns002
NS002_STATE_PATH="$(pwd)/.local/ns002/terraform.tfstate"

tofu -chdir=01-lab/hcl/netscaler init \
  -backend-config="path=${NS002_STATE_PATH}"
tofu -chdir=01-lab/hcl/netscaler fmt -check
tofu -chdir=01-lab/hcl/netscaler validate
tofu -chdir=01-lab/hcl/netscaler providers
```

Le state est isolé du module, sous `.local/ns002/`, et conserve les IDs des objets ADC. Garder ce fichier pour les reprises ; le state durable sera traité dans NS-003. Après déplacement du dépôt, traiter explicitement le changement de chemin du backend et conserver le state existant, sans appliquer à partir d’un state vide sur des objets déjà créés.

## 4. Planifier puis créer ou mettre à jour

```bash
tofu -chdir=01-lab/hcl/netscaler plan -detailed-exitcode
NS002_PLAN_EXIT=$?
printf 'Code du plan : %s\n' "$NS002_PLAN_EXIT"
```

Codes : 0 = aucun changement ; 1 = erreur ; 2 = changements proposés. Capturer le code immédiatement. Première création sur lab vierge : cinq ajouts attendus. Reprise d’un LB existant avec state et entrées inchangés : plan vide attendu. À la clôture de NS-002, le LB a été détruit et le state ne suit plus de ressources : cinq créations sont donc attendues pour le recréer. Vérifier que le plan ne touche que les objets NS-002.

Après inspection :

```bash
tofu -chdir=01-lab/hcl/netscaler apply
tofu -chdir=01-lab/hcl/netscaler state list
docker exec poc-netscaler-cpx \
  /var/netscaler/bins/cli_script.sh "show lb vserver poc-ns002-http"
```

apply recalcule le plan et demande confirmation. Attendu après création : cinq ressources suivies, virtual server UP, deux membres actifs. Un échec partiel exige d’examiner le state et l’ADC avant toute nouvelle tentative.

## 5. Tester trafic et convergence

```bash
for request in $(seq 1 20); do
  printf '%02d : ' "$request"
  curl -fsS --connect-timeout 5 --max-time 10 \
    http://127.0.0.1:18080/ || break
done

tofu -chdir=01-lab/hcl/netscaler plan -detailed-exitcode
NS002_PLAN_EXIT=$?
printf 'Code du plan : %s\n' "$NS002_PLAN_EXIT"
```

Attendu : vingt succès avec A/B et plan vide (code 0). La boucle s’arrête sur erreur : moins de vingt lignes réussies n’est pas un PASS. Les publications du Compose sont IPv4 ; utiliser `127.0.0.1` évite la tentative initiale sur `::1` refusée.

## 6. Changer la méthode

Pour rejouer ce cas, partir de ROUNDROBIN puis demander LEASTCONNECTION :

```bash
export TF_VAR_lb_method="LEASTCONNECTION"
tofu -chdir=01-lab/hcl/netscaler plan
# Attendu : uniquement la méthode du virtual server modifiée en place
tofu -chdir=01-lab/hcl/netscaler apply

docker exec poc-netscaler-cpx \
  /var/netscaler/bins/cli_script.sh "show lb vserver poc-ns002-http"
docker exec poc-netscaler-cpx \
  /var/netscaler/bins/cli_script.sh "show lb parameter"
```

Puis refaire la section 5. Attendu : méthode configurée LEASTCONNECTION, trafic réussi et plan vide. À la session validée, la méthode courante reste Round Robin en phase startup ; Start RR Factor vaut 0. Un test temporaire global startupRRFactor=1 a ensuite montré la disparition de la ligne Current Method Round Robin ; aucun test concurrent n’a qualifié la répartition Least Connection. Le retour à la valeur initiale 0 est confirmé à la clôture (section 8).

## 7. Retirer puis rétablir B

```bash
NS002_BACKENDS_ORIGINAL="$TF_VAR_backends"
export TF_VAR_backends="$(printf '%s' "$NS002_BACKENDS_ORIGINAL" \
  | jq -c 'del(.b)')"

tofu -chdir=01-lab/hcl/netscaler plan
# Attendu : destruction du seul binding backend["b"]
tofu -chdir=01-lab/hcl/netscaler apply

docker exec poc-netscaler-cpx \
  /var/netscaler/bins/cli_script.sh "show lb vserver poc-ns002-http"

for request in $(seq 1 10); do
  printf '%02d : ' "$request"
  curl -fsS --connect-timeout 5 --max-time 10 \
    http://127.0.0.1:18080/ || break
done
curl -fsS http://127.0.0.1:18082/

tofu -chdir=01-lab/hcl/netscaler plan -detailed-exitcode
NS002_PLAN_EXIT=$?
printf 'Code du plan : %s\n' "$NS002_PLAN_EXIT"
```

Attendu : un membre actif A, dix réponses A via LB, B toujours accessible directement, plan vide. Ne pas réexécuter la sauvegarde NS002_BACKENDS_ORIGINAL après retrait : elle écraserait l’entrée contenant A et B.

```bash
export TF_VAR_backends="$NS002_BACKENDS_ORIGINAL"
tofu -chdir=01-lab/hcl/netscaler plan
# Attendu : ajout du seul binding backend["b"]
tofu -chdir=01-lab/hcl/netscaler apply
docker exec poc-netscaler-cpx \
  /var/netscaler/bins/cli_script.sh "show lb vserver poc-ns002-http"
```

Refaire la section 5 : deux membres actifs, A/B observés et plan vide. Si le terminal a été fermé, reconstituer A/B par la section 2 plutôt que restaurer une variable disparue.

## 8. Rejouer le remplacement du port avec la correction HCL

Le module doit inclure ce bloc dans `citrixadc_lbvserver_servicegroup_binding.http` :

```hcl
lifecycle {
  replace_triggered_by = [citrixadc_lbvserver.http.port]
}
```

Sans ce bloc, le test a nécessité deux apply : remplacement du vserver puis réparation de la liaison au pool. Avec ce bloc, le retour 8081 → 8080 a convergé en un seul apply. Le remplacement peut interrompre le trafic ; aucune continuité n’est garantie.

Vérifier le paramètre global après tout test temporaire de startup (valeur 0 confirmée à la clôture de NS-002) :

```bash
docker exec poc-netscaler-cpx \
  /var/netscaler/bins/cli_script.sh "show lb parameter"
# Si le facteur n’est pas à sa valeur initiale 0, rétablir dans ce lab isolé :
# docker exec poc-netscaler-cpx \
#   /var/netscaler/bins/cli_script.sh "set lb parameter -startupRRFactor 0"
```

Depuis le LB courant sur 8080 :

```bash
export TF_VAR_lb_port=8081
tofu -chdir=01-lab/hcl/netscaler fmt -check
tofu -chdir=01-lab/hcl/netscaler validate
tofu -chdir=01-lab/hcl/netscaler plan
# Attendu avec correction : 2 ajouts / 2 suppressions, vserver et liaison uniquement
tofu -chdir=01-lab/hcl/netscaler apply

docker exec poc-netscaler-cpx \
  /var/netscaler/bins/cli_script.sh "show lb vserver poc-ns002-http"
CPX_IP="$TF_VAR_vip"
kubectl --context kind-netscaler-provider run ns002-port-check \
  --image=curlimages/curl:8.12.1 --restart=Never \
  --command -- curl -fsS --connect-timeout 5 --max-time 10 \
  "http://${CPX_IP}:8081/"
kubectl --context kind-netscaler-provider wait \
  --for=jsonpath='{.status.phase}'=Succeeded pod/ns002-port-check --timeout=30s
kubectl --context kind-netscaler-provider logs ns002-port-check
kubectl --context kind-netscaler-provider delete pod ns002-port-check

tofu -chdir=01-lab/hcl/netscaler plan -detailed-exitcode
NS002_PLAN_EXIT=$?
printf 'Code du plan : %s\n' "$NS002_PLAN_EXIT"
```

Attendu : UP, deux membres actifs, réponse A ou B et plan 0. Le test HTTP sur 8081 après réparation n’avait pas produit de réponse visible dans les preuves partagées ; cette variante de capture des logs est une procédure de rejeu, pas un résultat acquis. Si le wait échoue, examiner logs et statut. Le port WSL 18080 reste publié vers CPX:8080 et ne teste pas 8081.

Revenir au port publié pour poursuivre le lab :

```bash
export TF_VAR_lb_port=8080
tofu -chdir=01-lab/hcl/netscaler plan
# Attendu : vserver + liaison remplacés ; pool et membres préservés
tofu -chdir=01-lab/hcl/netscaler apply
```

Puis refaire les contrôles CLI et la section 5. Retour corrigé effectivement validé : UP, deux membres, 10 succès (5 A / 5 B), plan 0 dès le premier apply.

## 9. Supprimer les objets NS-002 en conservant le lab

```bash
tofu -chdir=01-lab/hcl/netscaler plan -destroy
# Attendu si les deux membres sont présents : 0 ajout, 0 modification, 5 suppressions
# Vérifier que le périmètre contient uniquement les ressources NS-002
tofu -chdir=01-lab/hcl/netscaler destroy

tofu -chdir=01-lab/hcl/netscaler state list

docker exec poc-netscaler-cpx \
  /var/netscaler/bins/cli_script.sh "show lb vserver poc-ns002-http"
docker exec poc-netscaler-cpx \
  /var/netscaler/bins/cli_script.sh "show serviceGroup poc-ns002-pool"

curl -fsS --connect-timeout 5 --max-time 10 http://127.0.0.1:18081/
curl -fsS --connect-timeout 5 --max-time 10 http://127.0.0.1:18082/
```

Résultat validé : cinq ressources détruites, aucune adresse dans le state, No such resource pour le vserver et le pool, réponses backend-a et backend-b préservées. Ces erreurs CLI sont le résultat attendu du contrôle d’absence. Les objets parents absents ne portent plus leurs bindings ; aucun inventaire exhaustif ADC n’a été réalisé.

Conserver le state local et les données CPX. Un plan normal après ce destroy proposerait cinq créations ; le HCL reste présent. Ne pas confondre nettoyage nominal, arrêt du lab et suppression du state.

## 10. Rejouer le backend Kubernetes et la reprise — NS-003

Procédure complète, commandes et résultats dans [NS-003](../00-docs/spikes/NS-003.md). Le module dédié est `01-lab/hcl/netscaler-state/` ; il reprend le module NS-002 corrigé et ajoute lb_name/pool_name.

| Exécution | Backend | Entrées ADC | Trafic |
|---|---|---|---|
| A | namespace netscaler-state, workspace default, suffixe ns003-a | poc-ns003-a-http / poc-ns003-a-pool, port 8080 | WSL 127.0.0.1:18080 |
| Reprise A | Identique à A, répertoire neuf | Identiques à A | Aucun nouvel apply |
| B | Même namespace/workspace, suffixe ns003-b | poc-ns003-b-http / poc-ns003-b-pool, port 8081 | Pod vers IP CPX:8081 |

Rejeu : préparer namespace et droits ; initialiser le module A ; exporter credentials/IP et noms A ; plan/apply et trafic ; sauvegarder le state ; initialiser un répertoire neuf sur le même backend et comparer IDs/lineage/serial. Pour B, utiliser un autre répertoire et suffixe, et des overrides de noms/port dans un sous-shell pour préserver les variables A. Les commandes exactes sont dans le CR lié ; aucun state ou .terraform ne doit être copié pour le test de reprise.

Résultats acquis : A 20 succès, plan 0 ; reprise A diff identité vide ; B lineage distinct et 20 succès ; restauration B après suppression contrôlée de son Secret, sans force, lineage conservé, serial 2 → 3 et plan 0 ; destruction B sans effet sur A ; destruction A et backends préservés.

La suppression du Secret de B est un test de perte maîtrisée avec sauvegarde vérifiée et writers arrêtés, pas une méthode normale de nettoyage. Aucun plan/init/apply entre la perte et le state push. Au rejeu, utiliser les lineages du nouveau test, pas les UUID historiques. Ne pas restaurer les snapshots pré-destroy comme état courant après suppression des objets.

À la sortie de NS-003, A et B sont supprimés ; namespace et sauvegardes sont conservés. Un rejeu commence donc par cinq créations sur un state ne suivant plus de ressources. Kubernetes dans kind n’assure pas la durabilité après reset du cluster. Le redémarrage du provider, ses droits et sa sélection de state ont été qualifiés dans NS004 (sections suivantes) ; la contention des locks reste à traiter en NS008.

## 11. Installer le provider Crossplane OpenTofu — NS004

NS004 utilise le MR namespaced `opentofu.m.upbound.io/v1beta1`. Procédure et réserves complètes dans [NS004](../00-docs/spikes/NS-004.md). Pas de commande tofu locale dans cette chaîne : OpenTofu 1.10.0 est embarqué dans le provider Crossplane v1.1.8 ; CitrixADC 2.3.0 reste le provider Terraform du module.

Créer `01-lab/crossplane/ns004/provider.yaml` avec :

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-opentofu
spec:
  package: xpkg.upbound.io/upbound/provider-opentofu:v1.1.8
```

```bash
mkdir -p 01-lab/crossplane/ns004
kubectl --context kind-netscaler-provider apply \
  -f 01-lab/crossplane/ns004/provider.yaml
kubectl --context kind-netscaler-provider get providers.pkg.crossplane.io
kubectl --context kind-netscaler-provider get pods -n crossplane-system
```

Attendu : provider Installed/Healthy True, pod Running. Au rejeu, relever le nom du pod, sa version `tofu version` et son ServiceAccount ; le nom initial était `provider-opentofu-97b0250cf8b1`. Ne pas supposer qu’il reste identique après mise à jour du package.

## 12. Préparer les accès et le ProviderConfig NS004

```bash
kubectl --context kind-netscaler-provider create namespace netscaler-state \
  --dry-run=client -o yaml \
  | kubectl --context kind-netscaler-provider apply -f -
kubectl --context kind-netscaler-provider create namespace netscaler-ns004 \
  --dry-run=client -o yaml \
  | kubectl --context kind-netscaler-provider apply -f -

CPX_PASSWORD="$(docker exec poc-netscaler-cpx \
  cat /var/deviceinfo/random_id)"
printf '%s' "$CPX_PASSWORD" \
  | kubectl --context kind-netscaler-provider \
      create secret generic ns004-nitro \
      -n netscaler-ns004 \
      --from-file=NS_PASSWORD=/dev/stdin \
      --dry-run=client -o yaml \
  | kubectl --context kind-netscaler-provider apply -f -
```

Employer le mot de passe actif si celui de nsroot a été changé. Le Secret contient une clé `NS_PASSWORD` ; aucune valeur secrète ne doit être inscrite dans le manifeste ou Git.

Vérifier les droits du ServiceAccount réellement observé :

```bash
NS004_PROVIDER_SA="provider-opentofu-97b0250cf8b1"
NS004_PROVIDER_ID="system:serviceaccount:crossplane-system:${NS004_PROVIDER_SA}"
kubectl --context kind-netscaler-provider auth can-i get secret/ns004-nitro \
  -n netscaler-ns004 --as="$NS004_PROVIDER_ID"
for resource in secrets leases.coordination.k8s.io; do
  for verb in get list create update patch delete; do
    printf '%s %s : ' "$verb" "$resource"
    kubectl --context kind-netscaler-provider auth can-i "$verb" "$resource" \
      -n netscaler-state --as="$NS004_PROVIDER_ID"
  done
done
```

Tous les contrôles ont répondu yes dans le lab qualifié. En cas de no, corriger les droits avant création du Workspace ; aucune règle RBAC supplémentaire n’a été nécessaire dans la session testée. Ce contrôle n’établit pas le moindre privilège.

Créer `01-lab/crossplane/ns004/provider-config.yaml` :

```yaml
apiVersion: opentofu.m.upbound.io/v1beta1
kind: ProviderConfig
metadata:
  name: ns004
  namespace: netscaler-ns004
spec:
  configuration: |
    terraform {
      required_version = ">= 1.10.0, < 1.11.0"

      required_providers {
        citrixadc = {
          source  = "registry.terraform.io/citrix/citrixadc"
          version = "2.3.0"
        }
      }

      backend "kubernetes" {
        namespace         = "netscaler-state"
        secret_suffix     = "ns004"
        in_cluster_config = true
      }
    }

    provider "citrixadc" {}
```

```bash
kubectl --context kind-netscaler-provider apply \
  -f 01-lab/crossplane/ns004/provider-config.yaml
kubectl --context kind-netscaler-provider get \
  providerconfigs.opentofu.m.upbound.io -n netscaler-ns004
```

## 13. Générer et appliquer le manifeste du MR Workspace

La génération suivante prépare un LB A/B sur les IP actuelles. Elle remplace workspace.yaml : l’utiliser au démarrage d’un rejeu initial, pas pour conserver un scénario de membres modifié. Pour une simple reprise réseau, suivre la section 1.1 et actualiser seulement les champs concernés.

```bash
CPX_IP="$(docker inspect poc-netscaler-cpx \
  --format '{{with index .NetworkSettings.Networks "kind"}}{{.IPAddress}}{{end}}')"
BACKEND_A_IP="$(docker inspect poc-netscaler-backend-a \
  --format '{{with index .NetworkSettings.Networks "kind"}}{{.IPAddress}}{{end}}')"
BACKEND_B_IP="$(docker inspect poc-netscaler-backend-b \
  --format '{{with index .NetworkSettings.Networks "kind"}}{{.IPAddress}}{{end}}')"

cat > 01-lab/crossplane/ns004/workspace.yaml <<EOF
apiVersion: opentofu.m.upbound.io/v1beta1
kind: Workspace
metadata:
  name: ns004-http
  namespace: netscaler-ns004
  annotations:
    crossplane.io/external-name: ns004-http
spec:
  providerConfigRef:
    kind: ProviderConfig
    name: ns004
  forProvider:
    source: Inline
    inlineFormat: HCL
    enableTofuCLILogging: true
    env:
      - name: NS_URL
        value: "http://${CPX_IP}:9080"
      - name: NS_LOGIN
        value: nsroot
      - name: NS_PASSWORD
        secretKeyRef:
          name: ns004-nitro
          key: NS_PASSWORD
    varmap:
      vip: "${CPX_IP}"
      lb_port: 8080
      lb_method: ROUNDROBIN
      backends:
        a:
          ip: "${BACKEND_A_IP}"
          port: 8080
        b:
          ip: "${BACKEND_B_IP}"
          port: 8080
    module: |
      variable "vip" {
        type = string
      }

      variable "lb_port" {
        type = number
      }

      variable "lb_method" {
        type = string
      }

      variable "backends" {
        type = map(object({
          ip   = string
          port = number
        }))
      }

      resource "citrixadc_lbvserver" "http" {
        name            = "poc-ns004-http"
        servicetype     = "HTTP"
        ipv46           = var.vip
        port            = var.lb_port
        lbmethod        = var.lb_method
        persistencetype = "NONE"
      }

      resource "citrixadc_servicegroup" "http" {
        servicegroupname = "poc-ns004-pool"
        servicetype      = "HTTP"
      }

      resource "citrixadc_servicegroup_servicegroupmember_binding" "backend" {
        for_each         = var.backends
        servicegroupname = citrixadc_servicegroup.http.servicegroupname
        ip               = each.value.ip
        port             = each.value.port
      }

      resource "citrixadc_lbvserver_servicegroup_binding" "http" {
        name             = citrixadc_lbvserver.http.name
        servicegroupname = citrixadc_servicegroup.http.servicegroupname

        lifecycle {
          replace_triggered_by = [
            citrixadc_lbvserver.http.port
          ]
        }
      }

      output "lb_name" {
        value = citrixadc_lbvserver.http.name
      }

      output "lb_port" {
        value = citrixadc_lbvserver.http.port
      }
EOF
```

Valider puis appliquer :

```bash
kubectl --context kind-netscaler-provider apply --dry-run=server \
  -f 01-lab/crossplane/ns004/workspace.yaml
kubectl --context kind-netscaler-provider apply \
  -f 01-lab/crossplane/ns004/workspace.yaml
```

Définir cette fonction dans la session pour attendre la déclaration actuelle, puis lire ses conditions :

```bash
ns004_wait_current() {
  local ns004_generation
  ns004_generation="$(kubectl --context kind-netscaler-provider get \
    workspaces.opentofu.m.upbound.io ns004-http \
    -n netscaler-ns004 -o jsonpath='{.metadata.generation}')" || return
  kubectl --context kind-netscaler-provider wait \
    workspaces.opentofu.m.upbound.io/ns004-http \
    -n netscaler-ns004 \
    --for=jsonpath='{.status.conditions[?(@.type=="Synced")].observedGeneration}'="$ns004_generation" \
    --timeout=120s || return
  kubectl --context kind-netscaler-provider get \
    workspaces.opentofu.m.upbound.io ns004-http \
    -n netscaler-ns004 -o json | jq -e --argjson generation "$ns004_generation" '
      (.metadata.generation == $generation)
      and any(.status.conditions[]?;
        .type == "Synced" and .status == "True"
        and .observedGeneration == $generation)
      and any(.status.conditions[]?;
        .type == "Ready" and .status == "True")'
}
ns004_wait_current

kubectl --context kind-netscaler-provider get \
  workspaces.opentofu.m.upbound.io ns004-http \
  -n netscaler-ns004 -o json \
  | jq '{conditions: .status.conditions, outputs: .status.atProvider.outputs}'
```

Attendu : fonction réussie/true, Synced et Ready True sur la génération demandée ; outputs nom poc-ns004-http et port 8080. Le premier apply de la session qualifiée a atteint ces conditions en six secondes. Le wait attend une observation, puis jq vérifie son succès ; ne pas poursuivre sur timeout ou false. La fonction suppose qu’aucun autre writer ne modifie la spec pendant l’attente.

Tester le service :

```bash
docker exec poc-netscaler-cpx \
  /var/netscaler/bins/cli_script.sh "show lb vserver poc-ns004-http"
for request in $(seq 1 20); do
  printf '%02d : ' "$request"
  curl -fsS --connect-timeout 5 --max-time 10 \
    http://127.0.0.1:18080/ || break
done
```

Attendu : UP/deux membres, vingt succès A/B. Ces contrôles sont acquis dans NS004 ; le rétablissement de A a ensuite donné dix réponses de chaque backend.

## 14. Vérifier le state et les verrous NS004

```bash
kubectl --context kind-netscaler-provider get \
  secrets,leases.coordination.k8s.io -n netscaler-state
kubectl --context kind-netscaler-provider get leases \
  -n netscaler-state \
  -o custom-columns='NAME:.metadata.name,HOLDER:.spec.holderIdentity'
```

Le MR ns004-http sélectionne le workspace OpenTofu ns004-http, suffixe ns004 : Secret tfstate-ns004-http-ns004 et Lease lock-tfstate-ns004-http-ns004. Un workspace default est également initialisé : son Secret a été vérifié vide (zéro instance), le workspace nommé contient cinq instances avec A/B. Les commandes de lecture résumée et d’identité ci-dessous ne publient pas le state brut.

```bash
mkdir -p .local/ns004
chmod 700 .local/ns004

ns004_state_identity() {
  kubectl --context kind-netscaler-provider get secret \
    tfstate-ns004-http-ns004 -n netscaler-state -o json \
    | python3 -c '
import sys, json, base64, gzip
secret = json.load(sys.stdin)
raw = base64.b64decode(secret["data"]["tfstate"])
if raw.startswith(b"\x1f\x8b"):
    raw = gzip.decompress(raw)
state = json.loads(raw)
instances = []
for resource in state.get("resources", []):
    for instance in resource.get("instances", []):
        instances.append({
            "type": resource.get("type"),
            "name": resource.get("name"),
            "key": instance.get("index_key"),
            "id": instance.get("attributes", {}).get("id")
        })
instances.sort(key=lambda item: json.dumps(item, sort_keys=True))
print(json.dumps({"lineage": state.get("lineage"),
                  "instances": instances}, indent=2, sort_keys=True))
'
}

(umask 077; ns004_state_identity > .local/ns004/identity-before-restart.json)
jq '{lineage, instances: (.instances | length)}' \
  .local/ns004/identity-before-restart.json
```

La lineage de la session qualifiée était 2958d18f-b9cf-8a8d-b723-9549e7a16274. Au rejeu, comparer la nouvelle identité à elle-même ; ne pas exiger cet UUID historique. Le résumé garde seulement lineage/IDs, sans serial ni attributs complets : ce n’est pas une sauvegarde de restauration.

## 15. Retirer et rétablir un membre via le MR

Modifier uniquement `spec.forProvider.varmap.backends` dans le fichier pour retirer A et conserver B. Sauvegarder le fichier, appliquer puis attendre :

```bash
kubectl --context kind-netscaler-provider apply \
  -f 01-lab/crossplane/ns004/workspace.yaml
ns004_wait_current

docker exec poc-netscaler-cpx \
  /var/netscaler/bins/cli_script.sh "show lb vserver poc-ns004-http"
for request in $(seq 1 10); do
  printf '%02d : ' "$request"
  curl -fsS --connect-timeout 5 --max-time 10 \
    http://127.0.0.1:18080/ || break
done
curl -fsS --connect-timeout 5 --max-time 10 http://127.0.0.1:18081/
```

Attendu : B seul actif, dix B via LB, A toujours joignable directement. Résultat acquis avec réserve : la session a aussi nécessité la reprise du lab et l’actualisation des IP (section 1.1). Ne pas revendiquer un retrait isolé sans changement réseau pour cette preuve historique.

Rétablir A avec son IP actuelle, conserver B, appliquer et attendre avec les mêmes commandes. Refaire les vingt requêtes de la section 13 : deux membres actifs, cinq instances, A/B. Ce rétablissement est validé dans la session.

## 16. Reprendre après redémarrage du provider

Après rétablissement de A/B, rafraîchir l’identité de référence par la fonction de la section 14 :

```bash
(umask 077; ns004_state_identity > .local/ns004/identity-before-restart.json)
kubectl --context kind-netscaler-provider get deployments -n crossplane-system
# Adapter au déploiement actuel :
NS004_PROVIDER_DEPLOY="provider-opentofu-97b0250cf8b1"
kubectl --context kind-netscaler-provider rollout restart \
  deployment/"$NS004_PROVIDER_DEPLOY" -n crossplane-system
kubectl --context kind-netscaler-provider rollout status \
  deployment/"$NS004_PROVIDER_DEPLOY" -n crossplane-system --timeout=120s
kubectl --context kind-netscaler-provider get pods -n crossplane-system

(umask 077; ns004_state_identity > .local/ns004/identity-after-restart.json)
diff -u .local/ns004/identity-before-restart.json \
  .local/ns004/identity-after-restart.json
```

Attendu et acquis : nouveau pod disponible, diff vide sur lineage/IDs. Retester HTTP avec la section 13. Le succès après restart ne prouve pas l’absence d’interruption pendant toute la fenêtre ni, avec les seuls IDs, l’absence d’opérations intermédiaires.

### Prouver l’activité du nouveau contrôleur

Modifier uniquement lb_method en LEASTCONNECTION, appliquer et appeler ns004_wait_current. Contrôler `show lb vserver poc-ns004-http` : méthode configurée LEASTCONNECTION, UP/deux membres. Puis remettre ROUNDROBIN, appliquer, attendre et contrôler à nouveau.

Résultats acquis : génération 5/LEASTCONNECTION, puis génération 6/ROUNDROBIN, toutes deux Synced True avec ReconcileSuccess et deux membres UP. Les générations sont historiques : la fonction attend celle du rejeu.

Les plans vides (code 0) ne sont **pas journalisés** dans v1.1.8, même avec enableTofuCLILogging=true ; erreurs et changements le sont. Ne pas attendre indéfiniment une ligne No changes. Les conditions synchronisées à la génération courante et la modification ADC après rollout démontrent que le nouveau contrôleur agit. Aucun code 0 direct du nouveau pod n’a été capturé.

## 17. Supprimer le MR et conserver le lab

Vérifier la politique :

```bash
kubectl --context kind-netscaler-provider get \
  workspaces.opentofu.m.upbound.io ns004-http \
  -n netscaler-ns004 -o json | jq '{
    managementPolicies: .spec.managementPolicies,
    finalizers: .metadata.finalizers
  }'
```

Dans la session : managementPolicies ["*"] et finalizer.managedresource.crossplane.io. Continuer si Delete est autorisé ("*" ou "Delete"). Garder provider, ProviderConfig et Secret NITRO pendant le nettoyage ; ne pas enlever le finalizer de force.

```bash
kubectl --context kind-netscaler-provider delete \
  workspaces.opentofu.m.upbound.io ns004-http \
  -n netscaler-ns004 --wait=false
kubectl --context kind-netscaler-provider wait --for=delete \
  workspaces.opentofu.m.upbound.io/ns004-http \
  -n netscaler-ns004 --timeout=120s

# Attendu : NotFound
kubectl --context kind-netscaler-provider get \
  workspaces.opentofu.m.upbound.io ns004-http -n netscaler-ns004

# Attendu : No such resource pour les deux objets
docker exec poc-netscaler-cpx \
  /var/netscaler/bins/cli_script.sh "show lb vserver poc-ns004-http"
docker exec poc-netscaler-cpx \
  /var/netscaler/bins/cli_script.sh "show serviceGroup poc-ns004-pool"

curl -fsS --connect-timeout 5 --max-time 10 http://127.0.0.1:18081/
curl -fsS --connect-timeout 5 --max-time 10 http://127.0.0.1:18082/
kubectl --context kind-netscaler-provider get \
  secrets,leases.coordination.k8s.io -n netscaler-state
```

Résultat acquis : MR NotFound, LB et pool absents, backends A/B disponibles, Secret et Lease du workspace ns004-http supprimés. Secret/Lease du workspace default-ns004 conservés, states NS003-a/b toujours distincts. Ce state default avait été vérifié vide avant la suppression ; aucune nouvelle lecture de son contenu n’a été fournie à la clôture.

Le manifeste Git reste présent avec A/B et ROUNDROBIN : un nouvel apply recrée le LB. Ne pas restaurer les identités/snapshots pré-suppression comme état courant. Si le wait échoue, lire conditions/logs et conserver les accès nécessaires au nettoyage.

## 18. Fin de session et prochaine amélioration

```bash
unset NS_PASSWORD NS_LOGIN NS_URL CPX_PASSWORD
unset TF_VAR_vip TF_VAR_backends TF_VAR_lb_method TF_VAR_lb_port
unset NS002_BACKENDS_ORIGINAL TF_VAR_lb_name TF_VAR_pool_name
```

Ce nettoyage d’environnement ne détruit aucun objet. Les LB étaient supprimés à la clôture nominale des spikes ; le rejeu de la section 1.2 a ensuite recréé NS004. Ce LB reste actif jusqu’à une nouvelle exécution de la section 17. Le lab et les composants d’accès restent disponibles. Le changement de port sous Crossplane n’a pas été exécuté ; il demeure complémentaire, avec sa correction HCL conservée.

L’actualisation des IP est désormais implémentée et validée pour les cas décrits en section 1.2, avec apply explicite. La suite est NS005 ; choisir explicitement de conserver ou supprimer le LB NS004 avant de tester d’autres ressources. Aucune actualisation périodique ou découverte réseau automatique par le contrôleur n’est ajoutée. Ne pas supprimer les states ou `.local/cpx` pour repartir propre avant d’avoir maîtrisé la propriété et le nettoyage des objets ADC.
