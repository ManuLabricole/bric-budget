# CONTEXT — État courant du projet
> **Template** — copier vers `CONTEXT.md` (privé, gitignoré). Maintenu par `/sync` en fin de session.
> Lu par Claude au démarrage. Source de vérité projet. Ne jamais modifier manuellement mid-session.
> Source de vérité roadmap : GitHub Project + Milestones.

---

## État Git

```
Branche courante : <branche>
Dernière PR      : <#N — titre — date>
Dernier commit   : <hash — message>
Tag prod         : <vX.Y.Z — date>
```

## Version courante

```
En prod  : <vX.Y.Z>
En cours : <vX.Y.Z — nom — milestone>
```

## Scope version en cours

```
🔄 #<N> <titre issue> — <statut>
🔜 #<N> <titre issue>
```

## Tests

```
make test     : <N passed / N failed — date>
make check    : <ruff / djlint / mypy>
make coverage : <% global>
```

## Config déploiement (à ne jamais perdre)

```
URL           : <url prod>
Build Command : <...>
Release Cmd   : <...>
```
