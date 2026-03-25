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
