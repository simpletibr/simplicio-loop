# simplicio-fast

[English](../README.md) · **Français**

Contexte sémantique binaire, incrémental et mappé en mémoire pour les agents logiciels.

Les sources normales produisent un cache dérivé `.sfast`, lu avec `mmap`. Les fichiers inchangés
sont réutilisés grâce à SHA-256 et les sources restent l'unique vérité.

Dans la POC de 500 fichiers et 1 500 symboles, la requête a été environ 23 fois plus rapide avec
95,65 % de CPU en moins. Ce résultat mesuré n'est pas une garantie universelle.

```bash
git clone https://github.com/wesleysimplicio/simplicio-fast
cd simplicio-fast && python -m pip install -e .
simplicio-fast build .
simplicio-fast doctor
simplicio-fast context UserService --root .
```

`simplicio-mapper` est obligatoire dans le flux officiel des agents et reste le producteur du
ContextGraph canonique. Voir [AGENTS.md](../AGENTS.md) et le [README complet](../README.md).
