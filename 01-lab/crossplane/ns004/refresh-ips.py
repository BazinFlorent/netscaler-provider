#!/usr/bin/env python3
"""Actualise les IP du Workspace NS004, sans changer les membres ni appliquer."""
import argparse
import copy
import ipaddress
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

try:
    import yaml
except ImportError:
    sys.exit("PyYAML requis : sur Arch Linux, installer le paquet python-yaml.")

CONTAINERS = {"a": "poc-netscaler-backend-a", "b": "poc-netscaler-backend-b"}
CPX = "poc-netscaler-cpx"


def field(node, name):
    if not isinstance(node, yaml.MappingNode):
        raise ValueError(f"Objet YAML attendu pour le champ {name}.")
    matches = [v for k, v in node.value if k.value == name]
    if len(matches) != 1:
        raise ValueError(f"Champ {name} absent ou dupliqué.")
    return matches[0]


def inspect_ips(names, network):
    result = subprocess.run(
        ["docker", "inspect", *names], check=True, text=True,
        capture_output=True, timeout=20,
    )
    ips = {}
    for container in json.loads(result.stdout):
        name = container["Name"].lstrip("/")
        if not container.get("State", {}).get("Running"):
            raise ValueError(f"Conteneur arrêté : {name}. Relancer le lab avant actualisation.")
        raw = container.get("NetworkSettings", {}).get("Networks", {}).get(network, {}).get("IPAddress")
        try:
            ip = ipaddress.IPv4Address(raw)
        except (ipaddress.AddressValueError, TypeError) as error:
            raise ValueError(f"IP IPv4 absente/invalide pour {name} sur le réseau {network}.") from error
        if ip.is_unspecified:
            raise ValueError(f"IP non attribuée pour {name}.")
        ips[name] = str(ip)
    if set(ips) != set(names):
        raise ValueError("Inventaire Docker incomplet.")
    if len(set(ips.values())) != len(ips):
        raise ValueError("Les conteneurs ne doivent pas partager la même IP dans ce lab.")
    return ips


def refresh_file(path, network="kind", dry_run=False):
    original = path.read_bytes()
    text = original.decode("utf-8")
    document = yaml.safe_load(text)
    if not isinstance(document, dict) or document.get("kind") != "Workspace":
        raise ValueError("Le fichier doit contenir un unique MR Workspace.")
    if document.get("apiVersion") != "opentofu.m.upbound.io/v1beta1":
        raise ValueError("API Workspace inattendue pour le lab NS004.")
    parameters = document["spec"]["forProvider"]
    variables = parameters["varmap"]
    backends = variables["backends"]
    if not isinstance(backends, dict) or set(backends) - set(CONTAINERS):
        raise ValueError("Les membres déclarés doivent être une map contenant uniquement a et/ou b.")
    env = parameters["env"]
    urls = [item for item in env if item.get("name") == "NS_URL"]
    if len(urls) != 1 or "value" not in urls[0]:
        raise ValueError("Une seule entrée NS_URL avec value explicite est requise.")
    if set(urls[0]) - {"name", "value"}:
        raise ValueError("NS_URL ne doit pas combiner value avec une autre source.")
    if not isinstance(variables["vip"], str):
        raise ValueError("vip doit être une chaîne.")
    for key, member in backends.items():
        if not isinstance(member, dict) or not isinstance(member.get("ip"), str):
            raise ValueError(f"IP explicite requise pour le membre {key}.")

    ips = inspect_ips([CPX, *(CONTAINERS[key] for key in backends)], network)
    expected = copy.deepcopy(document)
    new_parameters = expected["spec"]["forProvider"]
    new_variables = new_parameters["varmap"]
    next(item for item in new_parameters["env"] if item["name"] == "NS_URL")["value"] = f"http://{ips[CPX]}:9080"
    new_variables["vip"] = ips[CPX]
    for key in backends:
        new_variables["backends"][key]["ip"] = ips[CONTAINERS[key]]

    # Les positions des scalaires permettent de préserver commentaires, HCL et format.
    root = yaml.compose(text, Loader=yaml.SafeLoader)
    provider_node = field(field(root, "spec"), "forProvider")
    vars_node = field(provider_node, "varmap")
    env_node = field(provider_node, "env")
    url_nodes = [item for item in env_node.value if field(item, "name").value == "NS_URL"]
    targets = [(field(url_nodes[0], "value"), urls[0]["value"], f"http://{ips[CPX]}:9080", "NS_URL"),
               (field(vars_node, "vip"), variables["vip"], ips[CPX], "vip")]
    members_node = field(vars_node, "backends")
    for key, member in backends.items():
        targets.append((field(field(members_node, key), "ip"), member["ip"],
                        ips[CONTAINERS[key]], f"backends.{key}.ip"))

    edits = []
    for node, old, new, label in targets:
        if not isinstance(node, yaml.ScalarNode) or node.style in ("|", ">"):
            raise ValueError(f"Scalaire simple attendu : {label}.")
        if old != new:
            edits.append((node.start_mark.index, node.end_mark.index, json.dumps(new)))
            print(f"{label} : {old} -> {new}")
    updated = text
    for start, end, value in sorted(edits, reverse=True):
        updated = updated[:start] + value + updated[end:]
    if yaml.safe_load(updated) != expected:
        raise ValueError("Actualisation annulée : un champ inattendu aurait été modifié (alias YAML éventuel).")
    if not edits:
        print("IP déjà à jour ; fichier inchangé.")
        return False
    if dry_run:
        print("Simulation : fichier inchangé.")
        return True
    if path.read_bytes() != original:
        raise ValueError("Le fichier a changé pendant la préparation ; relancer.")
    mode = stat.S_IMODE(path.stat().st_mode)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f"Manifeste actualisé : {path}")
    print("Aucun apply exécuté. Vérifier le diff avant application.")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=Path(__file__).with_name("workspace.yaml"))
    parser.add_argument("--network", default="kind")
    parser.add_argument("--dry-run", action="store_true", help="Afficher les changements sans écrire.")
    args = parser.parse_args()
    try:
        refresh_file(args.file.resolve(strict=True), args.network, args.dry_run)
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError,
            subprocess.SubprocessError) as error:
        print(f"Échec : {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
