# simplicio-fast

[English](../README.md) · **Türkçe**

Yazılım ajanları için ikili, artımlı ve bellek eşlemeli anlamsal bağlam.

Normal kaynak dosyalarından türetilmiş `.sfast` önbelleği oluşturulur ve `mmap` ile okunur.
Değişmeyen dosyalar SHA-256 ile yeniden kullanılır; kaynak kod tek doğruluk kaynağıdır.

500 dosya ve 1.500 sembollük POC ölçümünde sorgu yaklaşık 23 kat hızlıydı ve %95,65 daha az CPU
kullandı. Bu ölçülmüş bir sonuçtur, evrensel garanti değildir.

```bash
git clone https://github.com/wesleysimplicio/simplicio-fast
cd simplicio-fast && python -m pip install -e .
simplicio-fast build .
simplicio-fast doctor
simplicio-fast context UserService --root .
```

Resmî ajan akışında `simplicio-mapper` zorunludur ve kanonik ContextGraph üreticisidir.
[AGENTS.md](../AGENTS.md) ve [tam README](../README.md) belgelerine bakın.
