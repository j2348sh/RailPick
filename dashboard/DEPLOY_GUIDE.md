# Streamlit Cloud 배포 가이드

## 1단계: GitHub 레포 생성

`dashboard/` 폴더를 별도 GitHub 레포로 만들거나, 기존 레포의 서브디렉토리로 사용합니다.

필요한 파일:
```
dashboard/
├── railpick_dashboard.py    # 메인 앱
├── requirements.txt         # 의존성
├── .streamlit/
│   └── config.toml          # 테마 설정
└── DEPLOY_GUIDE.md          # 이 파일
```

## 2단계: Streamlit Cloud 가입

1. https://share.streamlit.io 접속
2. GitHub 계정으로 로그인
3. "New app" 클릭

## 3단계: 앱 설정

- Repository: GitHub 레포 선택
- Branch: main
- Main file path: `railpick_dashboard.py` (또는 `dashboard/railpick_dashboard.py`)
- App URL: 원하는 이름 설정 (예: railpick-dashboard)

## 4단계: Secrets 설정 (중요!)

"Advanced settings" > "Secrets" 에 아래 내용 입력:

```toml
[firebase]
service_account_key = '여기에 서비스 계정 JSON 전체를 한 줄로 붙여넣기'
```

서비스 계정 키를 한 줄로 만드는 방법:
```bash
python3 -c "import json; print(json.dumps(json.load(open('railpick-firebase-adminsdk-fbsvc-0f8224f790.json'))))"
```

위 명령어 결과를 복사해서 `service_account_key = '...'` 안에 붙여넣으세요.

## 5단계: 배포

"Deploy!" 클릭하면 1-2분 내에 배포 완료.
고정 URL이 생성되며 브라우저 즐겨찾기에 등록하면 됩니다.

## 로컬 실행 (개발용)

```bash
cd dashboard
streamlit run railpick_dashboard.py
```

로컬에서는 `railpick-firebase-adminsdk-fbsvc-0f8224f790.json` 파일이 프로젝트 루트에 있으면 자동으로 사용됩니다.
