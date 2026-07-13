# simplicio-mapper

> 저장소를 사람과 AI 에이전트가 신뢰할 수 있는, 경계가 명확하고 질의 가능한 컨텍스트로 바꿉니다.

[![PyPI](https://img.shields.io/pypi/v/simplicio-mapper?color=0ea5e9&label=PyPI)](https://pypi.org/project/simplicio-mapper/)

[정식 README 및 모든 언어](../README.md)

<p align="center"><img src="../assets/llm-project-mapper-hero.png" alt="저장소가 증거 기반의 경계 있는 컨텍스트로 바뀌는 모습" width="100%"></p>

`simplicio-mapper`는 코드베이스를 `.simplicio/` 아래의 버전 관리 아티팩트로 변환합니다. 아키텍처, 심볼, 흐름, 규칙, 테스트, 작업별 컨텍스트 팩이 포함됩니다. Simplicio 생태계의 매핑 엔진으로서, 저장소 지식을 검사할 만큼 작고 감사할 만큼 명시적으로 만듭니다.

## 빠른 시작

```bash
pip install -U simplicio-mapper
simplicio-mapper index . --json
simplicio-mapper docs . --json
simplicio-mapper handoff . --goal "인증 흐름 추적" --token-budget 1200 --json
```

## 차별점

- **경계 있는 검색:** `handoff`와 `orient`는 저장소 전체를 조용히 프롬프트에 넣는 대신 관련성, 범위, 토큰 예산, 패널티, 충실도를 보고합니다.
- **변화를 따라가는 컨텍스트:** `sync`, `history`, `diff`, `delta`는 변경과 세션 사이에서 ContextGraph를 유지합니다.
- **증거 계약:** 공개 스키마, 검증, 신뢰도 태그, 동작 영수증, 증명서는 측정된 사실과 근거 없는 주장을 구분합니다.
- **실용적인 출력:** 프로젝트 맵, 아키텍처 문서, 엔드포인트와 화면 인벤토리, 흐름, 비즈니스 규칙, 온보딩 조사, 그래프 질의.

```bash
simplicio-mapper ask . impact "UserService" --json
simplicio-mapper sync . --check --json
simplicio-mapper contract validate .simplicio
simplicio-mapper doctor --contracts
```

Python 패키지가 정식 매핑 엔진입니다. npm의 [`@wesleysimplicio/llm-project-mapper`](https://www.npmjs.com/package/@wesleysimplicio/llm-project-mapper)는 보완적인 프로젝트 스타터입니다.

[문서 사이트](https://wesleysimplicio.github.io/simplicio-mapper/), [계약](../contracts/), [통합 가이드](../SIMPLICIO_INTEGRATION.md), [v0.23.1 릴리스](https://github.com/wesleysimplicio/simplicio-mapper/releases/tag/v0.23.1)를 참조하세요. 라이선스는 [MIT](../LICENSE)입니다.
