# 터미널 작업을 편하게 해 줄 유틸리티

## 디바이스 별 SSH 보안키 생성 및 등록

make_trnnel <username> <device_ip> <port> <hostname>
- <username>: SSH 접속에 사용할 사용자 이름
- <device_ip>: 디바이스의 IP 주소 (예: 192.168.1.100)
- <port>: SSH 접속에 사용할 포트 번호 (예: 22)
- <hostname>: 디바이스를 구분하기 위한 이름, 같은 IP에 여러 이름 가능 (예: my_device) (optional)

remove_trnnel <device_ip>
- <device_ip>: 삭제할 디바이스의 IP 주소


