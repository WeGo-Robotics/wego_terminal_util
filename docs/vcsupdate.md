# vcsupdate — 원격 로봇 vcstool 메타repo 업데이트 도구

원격 로봇 PC에 git 자격증명을 **영구 설치하지 않고**, 운영자 PC에서 GUI로 로봇의
vcstool 메타 워크스페이스(`.repos` 기반 메타 + 하위 repo)를 업데이트·관리하는 도구.
VSCode Source Control 처럼 repo별 브랜치·동기 상태(ahead/behind)·변경 수를 보여주고,
개별 git 작업(pull/push/sync/checkout 등)을 실행한다.

---

## 1. 동작 원리

- 운영자 PC GUI → `~/.ssh/config` 별칭으로 로봇에 SSH(paramiko) 접속.
- 접속 시 운영자의 **GitHub SSH 키**(보통 `~/.ssh/id_ed25519`)를 로봇의
  **`/dev/shm`(tmpfs = RAM)** 에 `0600` 으로 업로드하고, git/vcs 가 `GIT_SSH_COMMAND`
  로 그 키를 쓰게 한다. clone/pull/fetch/**push** 모두 이 키로 인증.
- **연결 종료 시 키 디렉토리 삭제** → 로봇 영구 디스크에 자격증명 미저장.
- `vcs import` 는 운영자 PC의 `.repos` 내용을 SSH stdin 으로 전달 → 로봇에 파일을
  미리 올릴 필요 없음.

### 왜 agent forwarding 이 아닌가

paramiko 의 SSH agent forwarding 은 Windows 운영자 PC에서 동작하지 않는다(forward
proxy 가 Unix 전용 `fcntl` 사용 → `Unable to connect to SSH agent`). 그래서 agent
forwarding 대신 RAM 키 주입 방식을 쓴다.

### 보안 트레이드오프

- 키가 로봇 RAM 으로 **잠시 전송**된다(영구 디스크 미저장, 종료 시 삭제).
  agent forwarding 처럼 키가 운영 PC를 절대 안 떠나는 것은 아니므로 **신뢰하는
  로봇에만** 사용.
- **passphrase 없는 키만 지원**(원격 ssh 가 비대화형으로 동작해야 함). 가급적
  전용 deploy 키 사용 권장.

---

## 2. 사전 요구사항

### 운영자 PC
- **Python 3.8+**, Tkinter(대부분 기본 포함).
- 의존성: `pip install -r requirements.txt` (`paramiko`, `pyyaml`).
- **passphrase 없는 GitHub SSH 키**. `~/.ssh/config` 의 `Host github.com` IdentityFile
  에서 자동 탐지하며, GUI 에서 직접 지정도 가능.
  ```
  Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519
  ```

### 로봇 PC
- **vcstool** (`pip install vcstool`), `git`.
- **Linux + `/dev/shm`**(tmpfs). 대부분의 ROS 로봇 기본 환경.
- 로봇 SSH 접속용 별칭이 운영자 `~/.ssh/config` 에 등록되어 있어야 함
  (`make_tunnel` 스크립트로 등록 가능).

---

## 3. 실행

```bash
python run_vcsupdate.py
```

### 입력 필드
| 필드 | 설명 |
|---|---|
| **Robot** | `~/.ssh/config` Host 별칭 드롭다운. 로봇 SSH 접속 대상 |
| **Workspace (remote)** | 로봇의 메타 워크스페이스 경로 (예: `radius-posco-ws`) |
| **src subdir** | `.repos` 가 import 되는 하위 폴더. 기본 `src`. 루트면 비움 |
| **.repos (local)** | 운영 PC 로컬의 `.repos` 정의 파일 (병합·import 용) |
| **Workers** | vcstool 병렬 워커 수 (기본 8) |
| **GitHub SSH key (local)** | 로봇에 주입할 키. 자동 탐지, 변경 가능 |

### 절차
1. **Robot** 선택 → **GitHub SSH key** 확인 → **Connect**. 연결되면 키를 로봇 RAM 에
   주입하고 지문을 표시.
2. **Workspace**, **src subdir**, **.repos** 지정.
3. **Refresh tree** 로 repo 트리를 채움.
4. 트리에서 repo 선택 후 작업(아래) 실행. 로그 창에서 실시간 진행 확인.
5. 창을 닫으면 로봇 RAM 의 키가 삭제됨.

> 마지막 입력값(robot 별칭, workspace, src subdir, .repos·키 경로, workers, 창 크기)을
> `%APPDATA%/vcsupdate/settings.json`(Linux/Mac: `~/.config/vcsupdate/`)에 저장해
> 다음 실행 시 복원한다. 비밀(키 내용 등)은 저장하지 않음(경로만).

---

## 4. 트리 뷰 (Source Control 스타일)

- **부모 노드** = 메타 워크스페이스. 루트가 git repo 면 `meta repo` 로 표시.
- **자식 노드** = 각 vcs 하위 repo (`src/<name>`).

| 컬럼 | 의미 |
|---|---|
| **Repo** | 경로 |
| **Branch** | 현재 체크아웃된 브랜치 |
| **↓↑** | upstream 대비 동기 상태. `↓{behind} ↑{ahead}`, 동기 상태면 `✓` |
| **Changes** | 변경된 파일 수 |
| **State** | `present`(정의+로봇), `missing`(정의만, 로봇에 없음→import 필요), `extra`(로봇만) |
| **Defined** | `.repos` 에 정의된 버전/브랜치 |

상태 색상: present=기본, missing=빨강, extra=파랑, dirty=주황.

`.repos` 키는 보통 prefix 없이(`radius-core`) 적히고 실제로는 `src/radius-core` 로
clone 되므로, **src subdir** 값으로 정의·실상태 경로를 맞춘다. 실상태는
`vcs custom --git --args status -sb` 로 중첩 repo 까지 짧은 형식으로 수집한다.

---

## 5. 작업

### 전체 일괄 (툴바)
- **vcs status** — 워크스페이스 전체 verbose 상태(로그).
- **vcs pull** — 모든 repo `vcs pull --nested`.
- **vcs import** — 로컬 `.repos` 기준 신규 clone/동기화 (`src` 하위).

### 선택 repo (툴바 / 우클릭 메뉴)
- **git pull** — `git pull --ff-only`.
- **git push** — `git push`.
- **↻ Sync** — `git pull --ff-only && git push` (VSCode Sync 와 동일).
- **git checkout…** — 브랜치/태그 전환(ref 화이트리스트 검증).
- 우클릭 추가: **git status / fetch / log / diff**.

다중 선택 시 순차 실행. **Cancel** 로 진행 중 작업 중단.

mutating 작업(pull/push/import/checkout/fetch/sync) 은 모두 주입된 키로 인증하며,
완료 후 트리를 자동 새로고침한다.

---

## 6. 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| `Unable to connect to SSH agent` | (해결됨) agent forwarding 미사용. 최신 버전 사용 |
| `git credential not available` | 키가 없거나 passphrase 보호됨. passphrase 없는 키 지정 |
| 모두 `missing`, 루트만 `extra` | **src subdir** 값 확인(기본 `src`). 정의/실상태 경로 prefix 불일치 |
| Branch 빈칸, Changes 가 일정한 수 | 구버전(verbose status 파싱). 최신 버전은 `status -sb` 사용 |
| `command not found` (exit 127) | 로봇에 vcstool/git 미설치 (`pip install vcstool`) |
| `Permission denied (publickey)` | GitHub 에 해당 키 미등록, 또는 잘못된 키 지정 |
| `/dev/shm` 관련 오류 | 로봇이 Linux + tmpfs 인지 확인 |

진단용 원격 명령:
```bash
ssh <robot> 'cd <workspace> && vcs custom . --nested --git --args status -sb | head -20'
```

---

## 7. 구조

```
run_vcsupdate.py          # 런처
vcsupdate/
├── ssh/ssh_config.py     # ~/.ssh/config 별칭/github 키 탐지 + paramiko 클라이언트
├── core/
│   ├── worker.py         # 워커 스레드 + 메시지 dataclass
│   ├── runner.py         # 실시간 스트리밍 실행 (stdin 주입 지원)
│   ├── credential.py     # github 키 → 로봇 /dev/shm 주입 + GIT_SSH_COMMAND + 정리
│   ├── commands.py       # vcs/git 명령 조립 + ref 검증 + cred 래핑 (순수 함수)
│   ├── repolist.py       # .repos + 실상태 병합 → 트리 모델 (순수 함수)
│   └── settings.py       # 입력값 영속화
└── ui/main_window.py     # Tkinter GUI (트리 + 로그)
tests/test_vcsupdate.py   # 단위 테스트 (명령/병합/파싱/자격증명)
```

### 패키징 (선택)
```bash
pyinstaller --onefile --windowed --name vcsupdate run_vcsupdate.py
```
