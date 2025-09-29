# OCR 기반 처방전/복약안내문 추출 API

이 프로젝트는 **Flask + Google Cloud Vision OCR + OpenAI API**를 활용하여  
이미지(처방전/복약안내문)를 업로드하면 텍스트를 추출하고 정규식/AI 요약을 통해  
**약 이름, 용법, 투약일수, 약효 요약** 등을 자동으로 제공하는 서버 애플리케이션입니다.  
Swagger UI를 통해 API 문서화 및 테스트를 지원합니다.

---

## 기능

- **OCR 처리**: Google Cloud Vision API를 사용하여 이미지 내 텍스트 추출
- **텍스트 정제**: 세로로 분리된 한글 텍스트를 자동 보정
- **처방전 인식**:
  - 병원명, 성명, 약 목록(약 이름, 용법, 투약일수) 추출
- **복약안내문 인식**:
  - 성명, 나이, 병원명 추출
  - `[효능제]`, `[처방례]`, `[주의]` 섹션 분석
  - OpenAI API를 통한 **한 문장 요약**
- **자동 문서 판별**: `처방전`, `복약안내문`, 또는 `알수없음` 자동 분류
- **Swagger API 문서**: `/ocr` 엔드포인트에 대한 문서화

---

## 기술 스택

- **Backend**: Python 3.12, Flask, Flask-CORS
- **OCR**: Google Cloud Vision API
- **AI 요약**: OpenAI GPT-4o-mini
- **환경 변수 관리**: python-dotenv
- **API 문서화**: flasgger (Swagger UI)

---

## 설치 및 실행 방법

### 1. 저장소 클론
```bash
git clone <your-repo-url>
cd <repo-directory>

2. 가상환경 생성 및 활성화
python3 -m venv venv
source venv/bin/activate   # Linux/Mac
venv\Scripts\activate      # Windows

3. 패키지 설치
pip install -r requirements.txt

4. 환경 변수 설정
프로젝트 루트에 .env 파일 생성:

env
OPENAI_API_KEY=sk-xxxx
GOOGLE_APPLICATION_CREDENTIALS=./gcp-key.json

5. 서버 실행
python app.py
서버는 http://localhost:5000 에서 실행됩니다.

API 사용법
엔드포인트
POST /ocr
요청 형식
multipart/form-data

파라미터: image (업로드할 이미지 파일)

응답 예시 (처방전)
{
  "type": "처방전",
  "병원명": "세란병원",
  "성명": "홍길동",
  "약목록": [
    {
      "약이름": "타이레놀정500mg",
      "용법": "아침, 저녁 식후30분",
      "투약일수": "28일"
    }
  ]
}

응답 예시 (복약안내문)
{
  "type": "복약안내문",
  "성명": "김철수",
  "나이": "65",
  "병원명": "서울병원",
  "약효목록": [
    {
      "효능": "소염진통제",
      "요약": "소염진통제이며 아침 복용 권장, 어지러움 주의."
    }
  ]
}

Swagger UI
서버 실행 후:
http://localhost:5000/apidocs
