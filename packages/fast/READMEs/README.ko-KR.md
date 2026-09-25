# simplicio-fast

[English](../README.md) · **한국어**

소프트웨어 에이전트를 위한 바이너리, 증분 및 메모리 매핑 시맨틱 컨텍스트입니다.

일반 소스 파일에서 파생 캐시 `.sfast`를 만들고 `mmap`으로 읽습니다. 변경되지 않은 파일은
SHA-256으로 재사용되며 소스 코드는 항상 유일한 진실의 원천입니다.

500개 파일과 1,500개 심볼 POC에서 쿼리는 약 23배 빨랐고 CPU 사용량은 95.65% 감소했습니다.
이는 측정 결과이며 모든 환경에 대한 보장은 아닙니다.

```bash
git clone https://github.com/wesleysimplicio/simplicio-fast
cd simplicio-fast && python -m pip install -e .
simplicio-fast build .
simplicio-fast doctor
simplicio-fast context UserService --root .
```

공식 에이전트 흐름에서는 `simplicio-mapper`가 필수이며 정규 ContextGraph를 생성합니다.
[AGENTS.md](../AGENTS.md)와 [전체 README](../README.md)를 참조하세요.
