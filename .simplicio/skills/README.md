# Simplicio skill catalog

This directory is the project-local, auditable source for the six Simplicio
capability skills. Each `SKILL.md` is indexed into Mapper's unified memory
store by:

```bash
python3 scripts/seed_simplicio_skills.py --root . --database .simplicio/memory.sqlite
```

The seed is idempotent: rerunning it updates changed skill content and reports
`unchanged` for the same content. The SQLite database is generated state; the
skill files remain the reviewable source of truth.
