# Lab NetScaler — procédure de rejeu

État au 7 octobre 2026 : NS-001 validé ; NS-002 terminé avec limites documentées. Création, trafic A/B, convergence, méthode configurée, membres, remplacement du port avec correction HCL et suppression nominale validés. À la clôture, le LB est supprimé ; CPX et les backends sont conservés.

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

Le script utilisateur lance Compose, affiche les services puis appelle les backends. Il ne remplace pas les tests NITRO ni l’ensemble de NS-001. Si le démarrage prend du temps, relancer les vérifications après disponibilité :

```bash
docker compose -f 01-lab/cpx/compose.yaml ps
docker compose -f 01-lab/cpx/compose.yaml logs --tail=80 cpx
curl -fsS http://127.0.0.1:18081/
curl -fsS http://127.0.0.1:18082/
```

Attendu : trois conteneurs Up, CPX démarré et réponses `backend-a`, `backend-b`. `config --quiet` vérifie le modèle Compose, pas la disponibilité des services.

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

## 10. Fin de session et prochaines étapes

```bash
unset NS_PASSWORD NS_LOGIN NS_URL
unset TF_VAR_vip TF_VAR_backends TF_VAR_lb_method TF_VAR_lb_port
unset NS002_BACKENDS_ORIGINAL
```

Ce nettoyage d’environnement ne détruit aucun objet. Si la section 9 a été exécutée, le LB est supprimé ; le state vide et les conteneurs restent conservés. Sans exécution de la section 9, le LB reste présent.

**À compléter après exécution :** backend durable NS-003 ; exécution Workspace NS-004. Ne pas supprimer le state ou `.local/cpx` pour « repartir propre » tant que la propriété et le nettoyage des objets ADC ne sont pas maîtrisés.
