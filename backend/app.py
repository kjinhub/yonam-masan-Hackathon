from flask import Flask, request, jsonify
from flask_cors import CORS
from google.cloud import vision
import os
import re
import openai
import json
from dotenv import load_dotenv
from flasgger import Swagger
openai.api_key = os.getenv("OPENAI_API_KEY")

# --- 환경변수 로드 ---
load_dotenv()

# --- Google Vision Client ---
client = vision.ImageAnnotatorClient.from_service_account_json(
    os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
)

# --- Flask + Swagger 설정 ---
app = Flask(__name__)
CORS(app)
swagger = Swagger(app)


def clean_ocr_text(raw_text: str) -> str:
    """OCR 결과에서 세로 분리된 항목들을 보정"""
    replacements = {
        "성\n명": "성명",
        "주\n민등록번호": "주민등록번호",
        "병원\n등록번호": "병원등록번호",
        "의료기관\n명": "의료기관명",
        "용\n법": "용법",
    }
    refined = raw_text
    for k, v in replacements.items():
        refined = refined.replace(k, v)
    return refined


def extract_prescription(text):
    """처방전 정규식 추출"""
    data = {}

    # --- 병원명 추출 (띄어쓰기 포함 허용 후 공백 제거) ---
    hospital = re.search(r"([가-힣\s]+병원|[가-힣\s]+의원)", text)
    if hospital:
        data["병원명"] = hospital.group(1).replace(" ", "")
        print("[추출됨] 병원명:", data["병원명"])

    # --- 성명 추출 ---
    name = re.search(r"(성명|환자명)\s*[: ]*\s*([가-힣]{2,3})", text)
    if name:
        data["성명"] = name.group(2)
        print("[추출됨] 성명:", data["성명"])
    else:
        name_alt = re.search(r"환\s*\n\s*([가-힣]{2,3})", text)
        if name_alt:
            data["성명"] = name_alt.group(1)
            print("[추출됨] 성명:", data["성명"])

    # === 약 정보 추출 ===
    lines = text.splitlines()
    drug_pattern = r"[가-힣A-Za-z]+\s*(정|캡슐|액)\s*\d*\.?\d*mg?"
    drug_names = [re.search(drug_pattern, line).group(0)
                  for line in lines if re.search(drug_pattern, line)]
    print("\n[약 이름 추출]", drug_names)

    days = [m for m in re.findall(r"\b\d{1,3}\b", text) if m in ["7", "14", "28", "30", "31"]]
    print("[투약일수 추출]", days)

    usage_lines = [line for line in lines if any(k in line for k in ["아침", "점심", "저녁", "식후", "취침전"])]
    print("[용법 추출]", usage_lines)

    medicines = []
    for i, drug in enumerate(drug_names):
        medicine = {
            "약이름": drug,
            "용법": usage_lines[i] if i < len(usage_lines) else None,
            "투약일수": (days[i] + "일") if i < len(days) else None
        }
        print("\n[매핑된 약 정보]", medicine)
        medicines.append(medicine)

    if medicines:
        data["약목록"] = medicines

    return data
import re
import os
import json
import openai

openai.api_key = os.getenv("OPENAI_API_KEY")

def extract_guideline(text):
    """복약안내문 추출 (성명, 나이, 병원명 + 효능·처방례·주의사항 한 문장 요약)"""
    data = {"type": "복약안내문", "약효목록": []}

    # --- 성명 추출 ---
    name = re.search(r"^([가-힣]{2,3})", text, re.MULTILINE)
    if name:
        data["성명"] = name.group(1)

    # --- 나이 추출 ---
    age = re.search(r"만(\d{1,3})세", text)
    if age:
        data["나이"] = age.group(1)

    # --- 병원명 추출 ---
    hospital = re.search(r"([가-힣]+병원|[가-힣]+의원)", text)
    if hospital:
        data["병원명"] = hospital.group(1)

    # --- 약효·처방례·주의사항 패턴 ---
    pattern = r"\[([가-힣]+제)\]\s*([\s\S]*?)(?=\[주의\])\[주의\]\s*([\s\S]*?)(?=\[[가-힣]+제|\Z)"
    matches = re.findall(pattern, text)

    for eff, usage, caution in matches:
        eff = eff.strip()
        usage = usage.strip().replace("\n", " ")
        caution = caution.strip().replace("\n", " ")

        # OpenAI 프롬프트 → 한 문장 요약
        prompt = f"""
        너는 의료 복약안내서를 요약하는 역할이야.
        아래 약 정보를 환자가 듣기 쉽게 한국어를 사용하여 한 문장으로 요약해라.
        반드시 효능명, 처방례, 주의사항의 핵심만 포함해야 하고 길게 설명하지 마라.
        출력은 JSON 형식으로 반환하라:
        {{
          "효능": "...",
          "요약": "..."
        }}

        효능: {eff}
        처방례: {usage}
        주의사항: {caution}
        """

        try:
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
            result_text = resp.choices[0].message["content"].strip()

            # ```json 코드블록 제거 처리
            if result_text.startswith("```"):
                result_text = re.sub(r"^```[a-zA-Z]*\n?", "", result_text)
                result_text = re.sub(r"```$", "", result_text)

            parsed = json.loads(result_text)
            data["약효목록"].append(parsed)
            print("\n[AI 요약 결과]", parsed)

        except Exception as e:
            # 실패 시 fallback
            summary = f"{eff}입니다. {usage.split('.')[0]}... {caution.split('.')[0]}..."
            fallback = {"효능": eff, "요약": summary}
            data["약효목록"].append(fallback)
            print("\n[AI 요약 실패 → fallback]", e)

    return data




@app.route("/ocr", methods=["POST"])
def ocr():
    """
    이미지 OCR → 처방전 / 복약안내문 자동 판별 후 추출
    ---
    consumes:
      - multipart/form-data
    parameters:
      - name: image
        in: formData
        type: file
        required: true
        description: 업로드할 이미지 파일 (처방전 또는 복약안내문)
    responses:
      200:
        description: OCR 및 정규식 추출 결과
        schema:
          type: object
          properties:
            type:
              type: string
              example: "처방전"
            병원명:
              type: string
              example: "세란병원"
            성명:
              type: string
              example: "홍길동"
            약목록:
              type: array
              items:
                type: object
                properties:
                  약이름:
                    type: string
                    example: "타이레놀정500mg"
                  용법:
                    type: string
                    example: "아침, 저녁 식후30분"
                  투약일수:
                    type: string
                    example: "28일"
            효능:
              type: array
              items:
                type: string
              example: ["소염진통제"]
            처방례:
              type: string
              example: "아침에 1정 복용"
            주의사항:
              type: string
              example: "어지러움 주의"
    """
    if "image" not in request.files:
        return jsonify({"error": "이미지 없음"}), 400

    image = request.files["image"].read()
    vision_image = vision.Image(content=image)
    response = client.text_detection(image=vision_image)
    texts = response.text_annotations

    if not texts:
        return jsonify({"text": ""})

    raw_text = texts[0].description.strip()
    print("\n=== OCR 원본 텍스트 ===")
    print(raw_text)

    refined_text = clean_ocr_text(raw_text)
    print("\n=== 보정된 텍스트 ===")
    print(refined_text)

    # --- 문서 유형 판별 ---
    if "처방전" in refined_text:
        doc_type = "처방전"
        result = extract_prescription(refined_text)
    elif "복약안내문" in refined_text:
        doc_type = "복약안내문"
        result = extract_guideline(refined_text)
    else:
        doc_type = "알수없음"
        result = {}

    result["type"] = doc_type
    print("\n=== 최종 추출 결과 ===")
    print(result)

    return jsonify(result)


if __name__ == "__main__":
    app.run(port=5000, debug=True)
