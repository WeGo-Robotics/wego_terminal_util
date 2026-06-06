# 터미널 작업을 편하게 해 줄 유틸리티

디바이스 SSH 접속을 위한 보안키 생성, 등록, 설정을 자동화하는 유틸리티입니다.
수동으로 키를 생성하거나 복사할 필요 없이, 명령어 한 줄로 SSH 접속 환경을 구성합니다.

---

## 지원 환경

| 플랫폼 | 스크립트 | 비고 |
|--------|---------|------|
| Linux / Mac | `make_tunnel.sh`, `remove_tunnel.sh` | Bash, `ssh-copy-id` 필요 |
| Windows | `make_tunnel.bat`, `remove_tunnel.bat` | PowerShell 포함 환경 (기본 제공) |

### 사전 요구사항

- **OpenSSH** 가 설치되어 있고 PATH에 등록되어 있어야 합니다.
- Linux/Mac: `ssh-copy-id` 명령어 사용 가능해야 합니다.
- Windows: PowerShell이 필요합니다 (Windows 10 이상 기본 포함).

---

## 파일 구조

```
wego_terminal_util/
├── README.md              # 문서
├── make_tunnel.sh         # Linux/Mac SSH 설정 스크립트
├── make_tunnel.bat        # Windows SSH 설정 스크립트
├── remove_tunnel.sh       # Linux/Mac SSH 설정 제거 스크립트
└── remove_tunnel.bat      # Windows SSH 설정 제거 스크립트
```

---

## 사용법

### 1. make_tunnel - SSH 접속 설정

디바이스에 대한 SSH 키를 생성하고 접속 환경을 자동 구성합니다.

#### 명령어

```bash
# Linux / Mac
./make_tunnel.sh <username> <device_ip> <port> <hostname>

# Windows
make_tunnel.bat <username> <device_ip> <port> <hostname>
```

#### 파라미터

| 파라미터 | 필수 | 설명 | 예시 |
|---------|------|------|------|
| `username` | O | SSH 접속에 사용할 사용자 이름 | `wego` |
| `device_ip` | O | 디바이스의 IP 주소 | `192.168.0.10` |
| `port` | O | SSH 포트 번호 | `22` |
| `hostname` | X | 디바이스를 구분하기 위한 별칭 (생략 시 IP 사용) | `GO2X_001` |

> 같은 IP에 여러 hostname을 지정하여 다중 접속 설정이 가능합니다.

#### 사용 예시

```bash
# 기본 사용
./make_tunnel.sh wego 192.168.0.10 22 GO2X_001

# hostname 생략 (IP를 별칭으로 사용)
./make_tunnel.sh wego 192.168.0.10 22

# 다른 포트 사용
./make_tunnel.sh admin 10.0.0.5 2222 DEV_SERVER
```

#### 대화형 모드

파라미터 없이 실행하면 대화형으로 입력받습니다:

```bash
./make_tunnel.sh
Enter target username: wego
Enter target IP/Hostname: 192.168.0.10
Enter SSH Port (Default 22): 22
```

#### 동작 과정

1. `~/.ssh/known_hosts`에서 기존 호스트 키를 제거 (호스트 키 변경 오류 방지)
2. 4096비트 RSA 키 쌍 생성 (`~/.ssh/id_rsa_<hostname>`)
3. 공개키를 원격 디바이스에 복사 및 등록
4. `~/.ssh/config`에 접속 설정 추가
5. 설정 완료 후 접속 명령어 안내

#### 설정 완료 후 접속

```bash
# hostname을 별칭으로 바로 접속
ssh GO2X_001
```

---

### 2. remove_tunnel - SSH 접속 설정 제거

디바이스에 대한 SSH 키와 접속 설정을 모두 삭제합니다.

#### 명령어

```bash
# Linux / Mac
./remove_tunnel.sh <device_ip>

# Windows
remove_tunnel.bat <device_ip>
```

#### 파라미터

| 파라미터 | 필수 | 설명 | 예시 |
|---------|------|------|------|
| `device_ip` | O | 삭제할 디바이스의 IP 주소 | `192.168.0.10` |

#### 사용 예시

```bash
./remove_tunnel.sh 192.168.0.10
```

#### 동작 과정

1. 해당 디바이스의 SSH 키 파일 삭제 (`id_rsa_<device>*`)
2. `~/.ssh/config`에서 관련 접속 설정 항목 제거

---

## 생성되는 SSH 설정

### 키 파일 위치

| 플랫폼 | 경로 |
|--------|------|
| Linux/Mac | `~/.ssh/id_rsa_<hostname>` |
| Windows | `%USERPROFILE%\.ssh\id_rsa_<hostname>` |

### SSH Config 항목 형식

`~/.ssh/config` (Windows: `%USERPROFILE%\.ssh\config`)에 아래 형식으로 자동 등록됩니다:

```
Host GO2X_001
    HostName 192.168.0.10
    User wego
    Port 22
    IdentityFile ~/.ssh/id_rsa_GO2X_001
```

---

## 활용 예시

### 여러 로봇 디바이스 관리

```bash
# 로봇 1호기 등록
./make_tunnel.sh wego 192.168.0.10 22 GO2X_001

# 로봇 2호기 등록
./make_tunnel.sh wego 192.168.0.11 22 GO2X_002

# 별칭으로 간편 접속
ssh GO2X_001
ssh GO2X_002

# 더 이상 사용하지 않는 디바이스 정리
./remove_tunnel.sh 192.168.0.10
```

### 개발 서버 접속 설정

```bash
# 개발 서버 등록
./make_tunnel.sh dev 10.0.0.100 22 DEV_MAIN

# 이후 간편 접속
ssh DEV_MAIN
```

---

## 폴더 비교/동기화 (Folder Sync)

두 폴더의 파일을 비교하고, 다른 파일을 골라서 동기화(복사)하는 GUI 프로그램입니다.
양쪽 폴더는 각각 **로컬** 또는 **SSH 원격(SFTP)** 이 될 수 있습니다.
위 `make_tunnel` 로 등록한 `~/.ssh/config` 의 Host 별칭을 그대로 골라서 접속합니다.

### 주요 기능

- **양방향 수동 동기화**: 파일별로 복사 방향(왼쪽→오른쪽 / 오른쪽→왼쪽)을 직접 선택.
- **비교 기준**: 먼저 파일 **크기**를 비교하고, 크기가 같으면 **sha256** 해시로 판정.
  (원격은 `sha256sum` 이 있으면 원격 실행, 없으면 SFTP 스트리밍 해시)
- **두 가지 비교 모드**
  - **Normal**: 폴더 전체를 재귀 탐색해 비교.
  - **Git**: 루트 repo + 중첩 repo의 git 정보로 추적/변경 파일만 비교.
    `.gitignore` 대상은 제외.
    중첩 repo는 트리에서 `.git` 를 스캔해 찾으므로 **git 서브모듈**뿐 아니라
    **vcstool**(`.repos` 기반 독립 클론)로 구성된 메타 워크스페이스도 지원.
    워크스페이스 루트가 git repo가 아니어도 하위 repo만 있으면 동작.
    (`build`/`install`/`log` 등 빌드 산출물 디렉토리는 스캔에서 제외)
    - **빠른 비교**: 파일 내용을 직접 해시하지 않고 **git blob oid**(`git ls-files -s`)로
      비교. 수정 안 된 파일은 git index 캐시라 사실상 공짜이고, 변경된 파일만
      디바이스에서 `git hash-object`로 oid 계산(전송 없음). 커밋이 같으면
      추적 파일은 oid가 동일 → 내용 안 읽고 SAME 판정. 대형 트리에서 크게 빨라짐.

### 사전 요구사항

- **Python 3.8+** 와 Tkinter (대부분의 배포판/설치본에 기본 포함).
- `paramiko` (SSH/SFTP):

```bash
pip install -r requirements.txt
```

### 실행

```bash
python run_foldersync.py
```

1. **Left / Right** 버튼으로 각 폴더의 소스를 지정 (Local 폴더 선택 또는 SSH 별칭 + 원격 경로).
   - 경로 입력칸은 **자동완성** 지원: 입력하면 하위 디렉토리/파일 목록이 뜨고, 선택하면 채워짐(디렉토리는 계속 드릴인). 원격은 SFTP로 조회.
2. **Normal / Git** 모드 선택 후 **Compare**.
3. 목록에서 파일을 선택하고 **Copy →** / **← Copy** (또는 우클릭 메뉴)로 동기화.

> 마지막 설정(좌/우 소스, Normal/Git 모드, Show identical, 창 크기)을 기억해
> 다음 실행 시 복원하고 자동 재접속합니다. 설정은 사용자 설정 폴더의
> `foldersync/settings.json` 에 저장됩니다 (비밀번호/passphrase는 저장 안 함).

### 파일 구조

```
foldersync/
├── fs/          # 로컬/SFTP 공통 파일시스템 추상화
├── compare/     # 크기→해시 비교 엔진
├── gitscope/    # Git 모드 탐색 범위 축소
├── sync/        # 파일 복사 엔진
├── core/        # 워커 스레드 + 컨트롤러
└── ui/          # Tkinter GUI
```

### 패키징 (선택)

```bash
pyinstaller --onefile --windowed --name foldersync run_foldersync.py
```

> Linux 타깃 바이너리는 Linux에서 빌드해야 합니다 (PyInstaller는 크로스 컴파일 불가).

## 원격 vcstool 메타repo 업데이트 (vcsupdate)

원격 로봇 PC에 git 자격증명을 **영구 설치하지 않고**, 운영자 PC에서 GUI로 로봇의
vcstool 메타 워크스페이스(`.repos` 기반 메타 + 하위 repo)를 업데이트·관리하는 도구입니다.
VSCode Source Control 처럼 repo별 브랜치·동기 상태(ahead/behind)·변경 수를 보여주고,
개별 git 작업(pull/push/sync/checkout 등)을 실행합니다.

- 자격증명은 접속 시 GitHub SSH 키를 로봇 **`/dev/shm`(RAM)** 에 주입하고 종료 시
  삭제 → 로봇 영구 디스크 미저장.
- 트리 뷰(메타+하위 repo), repo별/일괄 git·vcs 작업, 실시간 작업 로그.

```bash
python run_vcsupdate.py
```

> **자세한 사용법·보안 모델·트러블슈팅은 [docs/vcsupdate.md](docs/vcsupdate.md) 참고.**
