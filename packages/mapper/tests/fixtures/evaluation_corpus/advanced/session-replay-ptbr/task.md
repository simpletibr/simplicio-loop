# Replay de sessão

COMO analista de segurança
QUERO bloquear replay de sessão com nonce rotativo
PARA impedir reutilização de token já consumido.

AC01: nonce repetido invalida a sessão.
AC02: nonce novo é aceito e armazenado.
AC03: a regra principal fica no guard de replay de sessão.
