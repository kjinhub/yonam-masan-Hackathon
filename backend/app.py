from flask import Flask, request, jsonify
from flask_cors import CORS
from google.cloud import vision
import os
import re
import openai
from dotenv import load_dotenv
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
# 환경변수에서 OpenAI API Key 불러오기

app = Flask(__name__)
CORS(app)

# Google Vision Client
client = vision.ImageAnnotatorClient.from_service_account_json("gcp-key.json")

# --- [수정 추가] OCR 결과 저장소 (딕셔너리) ---
ocr_storage = {
    "처방전": None,
    "복약지침서": None
}

def extract_prescription(text):
    data = {}

    # 병원명
    hospital = re.search(r"([가-힣]+병원|[가-힣]+의원)", text)
    if hospital:
        data["병원명"] = hospital.group(1)

    # 성명
    name = re.search(r"(성명|환자명)[\s:]*([가-힣]{2,3})", text)
    if name:
        data["성명"] = name.group(2)

    # 약별 데이터 추출
    medicines = []
    lines = text.splitlines()
    for line in lines:
        # 약 이름
        drug_match = re.search(r"[가-힣A-Za-z]+(정|캡슐|액)\s?\d*mg?", line)
        if drug_match:
            drug_name = drug_match.group(0)

            # 용법
            usage = re.findall(r"(아침|점심|저녁|취침전|식전|식후\s?\d*분)", line)

            # 투약일수 (가장 큰 값만 선택)
            days = re.findall(r"(\d+)일", line)
            max_days = max([int(d) for d in days], default=None)

            medicines.append({
                "약이름": drug_name,
                "용법": usage,
                "투약일수": str(max_days) + "일" if max_days else None
            })

    if medicines:
        data["약목록"] = medicines

    return data


def extract_guideline(text):
    data = {}
    # 약 이름
    drug = re.search(r"[가-힣A-Za-z]+(정|캡슐|액)", text)
    if drug:
        data["약이름"] = drug.group(0)

    # 처방례
    usage = re.findall(r"\[처방례\]\s*([\s\S]*?)(?=\[|$)", text)
    if usage:
        try:
            completion = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "너는 약 복용 지침을 고령층이 이해하기 쉽게 요약하는 보조기다."},
                    {"role": "user", "content": f"복용 지침: {usage}\n\n이 문장을 간단하게 요약해줘."}
                ]
            )
            summarized = completion.choices[0].message["content"].strip()
            data["처방례"] = summarized
        except Exception as e:
            print("GPT Error:", e)
            data["처방례"] = " ".join(u[0] if isinstance(u, tuple) else u for u in usage)

    # 주의사항 / 효능
    caution = re.findall(r"\[주의사항\]\s*([\s\S]*?)(?=\[|$)", text)
    if caution:
        raw_caution = caution[0].strip() 
        try:
            completion = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "너는 약의 효능과 주의사항을 의미가 잘 통하도록 보정하는 보정기다."},
                    {"role": "user", "content": f"주의사항/효능 텍스트: {raw_caution}\n\n이 내용을 보정하고 효능은 예: '소염 진통제' 이런 식으로 완성해줘."}
                ]
            )
            refined_caution = completion.choices[0].message["content"].strip()
            data["주의사항"] = refined_caution
        except Exception as e:
            print("GPT Error:", e)
            data["주의사항"] = raw_caution

    return data


@app.route("/ocr", methods=["POST"])
def ocr():
    if "image" not in request.files:
        return jsonify({"error": "이미지 없음"}), 400

    # --- OCR 처리 ---
    image = request.files["image"].read()
    vision_image = vision.Image(content=image)
    response = client.text_detection(image=vision_image)
    texts = response.text_annotations

    if not texts:
        return jsonify({"text": ""})

    raw_text = texts[0].description.strip()

    # --- GPT 보정 ---
    try:
        completion = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "너는 OCR 결과를 사람이 읽기 좋은 자연스러운 문장으로 보정하는 보정기다."},
                {"role": "user", "content": f"OCR 결과: {raw_text}\n\n이 문장을 자연스럽게 보정해줘."}
            ]
        )
        refined_text = completion.choices[0].message["content"].strip()
    except Exception as e:
        print("GPT Error:", e)
        refined_text = raw_text  # 오류 시 원본 사용

    # --- 문서 분류 (GPT + refined_text 사용) ---
    try:
        completion = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "너는 OCR 결과가 어떤 문서인지 판별하는 보조기다."},
                {"role": "user", "content": f"OCR 결과: {refined_text}\n\n이 문서는 '처방전'인지 '복약지침서'인지 판단해. 이유는 말하지 말고 '처방전' 또는 '복약지침서' 중 하나만 답해."}
            ]
        )
        doc_type = completion.choices[0].message["content"].strip()
    except Exception as e:
        print("GPT Error:", e)
        # GPT 오류 시 fallback: 키워드 기반
        if "병원" in refined_text or "투약일수" in refined_text or "성명" in refined_text:
            doc_type = "처방전"
        else:
            doc_type = "복약지침서"

    # --- 문서별 처리 ---
    if doc_type == "처방전":
        result = extract_prescription(refined_text)
        result["type"] = "처방전"
        ocr_storage["처방전"] = result
    else:
        result = extract_guideline(refined_text)
        result["type"] = "복약지침서"
        ocr_storage["복약지침서"] = result

    return jsonify(result)



# --- [수정 추가] 저장된 결과 전체 불러오기 ---
@app.route("/ocr-results", methods=["GET"])
def get_results():
    return jsonify(ocr_storage)


if __name__ == "__main__":
    app.run(port=5000, debug=True)
