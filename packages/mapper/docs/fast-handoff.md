# Handoff canônico para o Simplicio Fast

O comando abaixo fornece ao processador mmap um envelope JSON inequívoco, sem
obrigá-lo a analisar texto de terminal nem a reler o código-fonte já coberto
pelo Mapper:

```bash
simplicio-mapper snapshot build --root .
simplicio-mapper fast-handoff . --base-commit "$(git rev-parse HEAD)"
```

Para atualização incremental, repita `--changed-path` para cada arquivo
alterado. O envelope `simplicio.mapper-fast-handoff/v1` contém geração, mapa
canônico da branch padrão, IDs afetados, caminhos, checksums e capacidades
negociáveis. `--expect-schema` recusa versões incompatíveis com uma mensagem
acionável. `--verify` detecta artefatos ausentes, corrompidos ou obsoletos.

Os recibos `.simplicio/fast-handoff-receipt.json` distinguem material
processado, reutilizado, degradado e fallback. Vinte slots podem compartilhar a
mesma geração e o mesmo `canonical_map.id`; as gravações são atômicas.

Rollback: consumidores podem ignorar o handoff e continuar usando os artefatos
JSON canônicos existentes. O Mapper permanece o produtor público e não expõe
offsets ou estruturas internas do mmap.
