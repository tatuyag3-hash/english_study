import streamlit as st
import json
import base64
import vertexai
from vertexai.generative_models import GenerativeModel
from vertexai.preview.vision_models import ImageGenerationModel
from google.oauth2 import service_account
from supabase import create_client, Client

# ==========================================
# 1. ページ全体の設定とデザイン
# ==========================================
st.set_page_config(page_title="えいごでおこづかい！", layout="centered")

st.markdown("""
    <style>
    .big-font { font-size:24px !important; font-weight: bold; }
    .allowance-text { font-size:30px !important; color: #ff4b4b; font-weight: bold;}
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 2. 初期設定（Supabase と Google Cloud）
# ==========================================
try:
    # Supabaseの認証設定
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # GCP (Vertex AI) の認証設定
    PROJECT_ID = st.secrets["GCP_PROJECT_ID"]
    gcp_credentials_dict = dict(st.secrets["gcp_service_account"])
    credentials = service_account.Credentials.from_service_account_info(gcp_credentials_dict)
    vertexai.init(project=PROJECT_ID, location="asia-northeast1", credentials=credentials)

except Exception as e:
    st.error("【システムエラー】Secretsの設定が完了していないか、形式が間違っています。")
    st.stop()

# ==========================================
# 3. バックエンド処理（パパのシステム）
# ==========================================
def calculate_unpaid_allowance():
    """未精算のお小遣いを計算する（数値計算はPython内で厳密に実行）"""
    try:
        response = supabase.table("learning_logs").select("*", count="exact").eq("is_cashed_out", False).eq("is_correct", True).execute()
        valid_count = response.count if response.count else 0
        reward_per_question = 1
        
        # Pythonによる数値計算処理
        total_allowance = valid_count * reward_per_question
        return total_allowance
    except:
        return 0

def fetch_question():
    """データベースから未使用の問題を1問持ってくる"""
    response = supabase.table("questions").select("*").eq("is_used", False).limit(1).execute()
    if response.data:
        return response.data[0]
    return None

def record_answer(question_id, is_correct):
    """解答結果を記録し、問題を使用済みにする"""
    supabase.table("learning_logs").insert({
        "question_id": question_id,
        "is_correct": is_correct,
        "time_taken_sec": 5.0
    }).execute()
    supabase.table("questions").update({"is_used": True}).eq("id", question_id).execute()

def execute_cash_out():
    """お小遣いを精算（リセット）する"""
    supabase.table("learning_logs").update({"is_cashed_out": True}).eq("is_cashed_out", False).execute()

def generate_and_stock_question_google(theme, target_word):
    """Google Gemini と Imagen 3 を使った問題・画像ストック機能"""
    
    # 1. Geminiによるテキスト生成
    text_model = GenerativeModel("gemini-1.5-flash")
    system_instruction = "あなたは小学生に初めて英語を教えるプロです。以下のJSONフォーマットのみを出力してください。\n{\"grade\": 5, \"category\": \"基礎単語\", \"question_text\": \"日本語の問題文\", \"choices\": [\"選択肢1\", \"選択肢2\", \"選択肢3\", \"選択肢4\"], \"correct_answer\": \"正解\"}\n絶対ルール：英語の文章は作らず、答えは名詞1単語または基本挨拶のみ。"
    prompt = f"{system_instruction}\n\nテーマ: {theme}\nターゲット単語: {target_word}\n条件: 日本語の楽しい状況説明を読んで、正しい英単語を4つの選択肢から選ばせること。"
    
    response = text_model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
    question_data = json.loads(response.text)
    
    # 2. Imagen 3による画像生成
    image_model = ImageGenerationModel.from_pretrained("imagegeneration@006")
    image_prompt = f"A warm, Japanese picture-book style watercolor illustration of: {theme}. The main subject ({target_word}) must be drawn large and clearly in the center. Light, pastel colors, soft and gentle atmosphere. ABSOLUTELY NO TEXT, NO LETTERS, NO WORDS in the image."
    
    image_result = image_model.generate_images(prompt=image_prompt, number_of_images=1, aspect_ratio="1:1")
    
    # バイナリデータをBase64に変換
    image_bytes = image_result[0]._image_bytes
    base64_encoded = base64.b64encode(image_bytes).decode("utf-8")
    base64_image_data = f"data:image/png;base64,{base64_encoded}"
    
    # 3. データベースへ保存
    insert_data = {
        "grade": question_data["grade"],
        "category": question_data["category"],
        "question_text": question_data["question_text"],
        "choices": question_data["choices"],
        "correct_answer": question_data["correct_answer"],
        "image_url": base64_image_data,
        "is_used": False
    }
    supabase.table("questions").insert(insert_data).execute()

# ==========================================
# 4. フロントエンド（画面）と演出
# ==========================================
def show_correct_animation():
    """正解時の巨大な〇アニメーション"""
    circle_html = """
        <style>
        .big-circle { font-size: 150px; color: #FF4B4B; text-align: center; font-weight: bold; margin: 0; animation: pop-in 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards; }
        @keyframes pop-in { 0% { opacity: 0; transform: scale(0.5); } 100% { opacity: 1; transform: scale(1); } }
        </style>
        <div class="big-circle">〇</div>
    """
    st.markdown(circle_html, unsafe_allow_html=True)
    st.balloons()

def render_learning_view():
    st.title("えいご クイズにちょうせん！✨")
    st.markdown(f"💰 今の おこづかい： <span class='allowance-text'>{calculate_unpaid_allowance()} 円</span>", unsafe_allow_html=True)
    st.divider()

    if 'current_question' not in st.session_state:
        st.session_state.current_question = fetch_question()
        st.session_state.answered = False

    q = st.session_state.current_question

    if not q:
        st.warning("もんだいが なくなっちゃった！パパに おねがいしてね。")
        return

    st.markdown(f"<p class='big-font'>{q['question_text']}</p>", unsafe_allow_html=True)
    if q.get('image_url'):
        st.image(q['image_url'], use_container_width=True)

    if not st.session_state.answered:
        cols = st.columns(2)
        for i, choice in enumerate(q["choices"]):
            with cols[i % 2]:
                if st.button(choice, use_container_width=True, key=f"btn_{i}"):
                    is_correct = (choice == q["correct_answer"])
                    record_answer(q["id"], is_correct)
                    st.session_state.answered = True
                    st.session_state.is_correct = is_correct
                    st.rerun()
    else:
        if st.session_state.is_correct:
            show_correct_animation()
            st.success("だいせいかい！🎉 1えん ゲット！")
        else:
            st.error(f"ざんねん… せいかいは 「{q['correct_answer']}」 でした！")
        
        if st.button("つぎの もんだいへ！", type="primary"):
            del st.session_state.current_question
            del st.session_state.answered
            st.rerun()

def render_dad_dashboard():
    st.title("👨 パパ用 管理ダッシュボード")
    st.metric(label="未精算のお小遣い残高", value=f"{calculate_unpaid_allowance()} 円")
    
    if st.button("お小遣いを精算する（支払い完了）", type="primary"):
        execute_cash_out()
        st.success("精算処理が完了しました。")
        st.rerun()
        
    st.divider()
    st.subheader("問題の自動生成・ストック")
    
    response = supabase.table("questions").select("*", count="exact").eq("is_used", False).execute()
    stock_count = response.count if response.count else 0
    st.write(f"現在の残りストック: {stock_count}問")
    
    with st.form("gen_form"):
        theme = st.text_input("テーマ", "サイゼリヤで食事")
        word = st.text_input("ターゲット単語", "pizza")
        if st.form_submit_button("AIで問題を1問生成する"):
            with st.spinner("AIが水彩画と問題を作成中...（約15秒かかります）"):
                generate_and_stock_question_google(theme, word)
            st.success("ストック完了しました！")
            st.rerun()

# ==========================================
# 5. ログイン（パスワード）分岐
# ==========================================
def main():
    user_type = st.sidebar.text_input("パスワード（ひみつのことば）", type="password")
    if user_type == "papa1234":
        render_dad_dashboard()
    elif user_type == "musume55":
        render_learning_view()
    else:
        st.title("えいごでおこづかいアプリ 🍒")
        st.write("ひだりの メニューから ひみつのことばを いれてね！")

if __name__ == "__main__":
    main()