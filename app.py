import streamlit as st
import json
from openai import OpenAI
from supabase import create_client, Client

# ==========================================
# 1. ページ全体の設定とデザイン
# ==========================================
st.set_page_config(page_title="えいごでおこづかい！", layout="centered")

# お嬢様向けのポップなデザイン設定（CSS）
st.markdown("""
    <style>
    .big-font { font-size:24px !important; font-weight: bold; }
    .allowance-text { font-size:30px !important; color: #ff4b4b; font-weight: bold;}
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 2. 初期設定（Streamlit Cloud用の秘密鍵読み込み）
# ==========================================
# ※開発時は st.secrets を使って安全に鍵を読み込みます
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
    
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    st.error("【パパへ】Streamlit Cloudの「Secrets」設定がまだ完了していません！")
    st.stop()

# ==========================================
# 3. バックエンド処理（パパのシステム）
# ==========================================
def calculate_unpaid_allowance():
    """未精算のお小遣いを計算する"""
    try:
        response = supabase.table("learning_logs").select("*", count="exact").eq("is_cashed_out", False).eq("is_correct", True).execute()
        valid_count = response.count if response.count else 0
        return valid_count * 1 # 1問1円
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
        "time_taken_sec": 5.0 # ※本来は時間を計測しますが今回は簡易化
    }).execute()
    supabase.table("questions").update({"is_used": True}).eq("id", question_id).execute()

def execute_cash_out():
    """お小遣いを精算（リセット）する"""
    supabase.table("learning_logs").update({"is_cashed_out": True}).eq("is_cashed_out", False).execute()

def generate_and_stock_question(theme, target_word):
    """AIで問題とイラストを生成してストックする"""
    system_prompt = """
    あなたは小学生に初めて英語を教えるプロの講師です。
    以下のJSONフォーマットのみを出力してください。
    {"grade": 5, "category": "基礎単語", "question_text": "日本語の問題文", "choices": ["選択肢1", "選択肢2", "選択肢3", "選択肢4"], "correct_answer": "正解"}
    絶対ルール：英語の文章は作らず、答えは「名詞1単語」または基本的な挨拶のみ。
    """
    user_prompt = f"ターゲット単語: {target_word}\nテーマ: {theme}\n条件: 日本語の楽しい状況説明を読んで、正しい英単語を4つの選択肢から選ばせること。"

    # 問題テキストの生成
    text_completion = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format={ "type": "json_object" }
    )
    question_data = json.loads(text_completion.choices[0].message.content)
    
    # 画像生成（水彩画風、文字なし）
    image_prompt = f"A warm, Japanese picture-book style watercolor illustration of: {theme}. The main subject ({target_word}) must be drawn large and clearly in the center. Light, pastel colors, soft and gentle atmosphere. ABSOLUTELY NO TEXT, NO LETTERS, NO WORDS in the image."
    image_response = openai_client.images.generate(
        model="dall-e-3", prompt=image_prompt, size="1024x1024", quality="standard", n=1,
    )
    
    # データベースへ保存
    insert_data = {
        "grade": question_data["grade"],
        "category": question_data["category"],
        "question_text": question_data["question_text"],
        "choices": question_data["choices"],
        "correct_answer": question_data["correct_answer"],
        "image_url": image_response.data[0].url,
        "is_used": False
    }
    supabase.table("questions").insert(insert_data).execute()

# ==========================================
# 4. フロントエンド（画面）と演出
# ==========================================
def show_correct_animation():
    """正解時の巨大な〇アニメーションと風船演出"""
    circle_html = """
        <style>
        .big-circle {
            font-size: 150px; color: #FF4B4B; text-align: center; font-weight: bold; margin: 0;
            animation: pop-in 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards;
        }
        @keyframes pop-in { 0% { opacity: 0; transform: scale(0.5); } 100% { opacity: 1; transform: scale(1); } }
        </style>
        <div class="big-circle">〇</div>
    """
    st.markdown(circle_html, unsafe_allow_html=True)
    st.balloons() # Streamlit標準の風船演出を同時発動

def render_learning_view():
    """お嬢様用 学習画面"""
    st.title("えいご クイズにちょうせん！✨")
    st.markdown(f"💰 今の おこづかい： <span class='allowance-text'>{calculate_unpaid_allowance()} 円</span>", unsafe_allow_html=True)
    st.divider()

    # 表示する問題を固定するための状態管理
    if 'current_question' not in st.session_state:
        st.session_state.current_question = fetch_question()
        st.session_state.answered = False

    q = st.session_state.current_question

    if not q:
        st.warning("もんだいが なくなっちゃった！パパに おねがいしてね。")
        return

    # 問題と画像の表示
    st.markdown(f"<p class='big-font'>{q['question_text']}</p>", unsafe_allow_html=True)
    if q.get('image_url'):
        st.image(q['image_url'], use_container_width=True)

    # 解答ボタンの表示（2列）
    if not st.session_state.answered:
        cols = st.columns(2)
        for i, choice in enumerate(q["choices"]):
            with cols[i % 2]:
                if st.button(choice, use_container_width=True, key=f"btn_{i}"):
                    is_correct = (choice == q["correct_answer"])
                    record_answer(q["id"], is_correct)
                    # 解答状態を保存して画面を再描画
                    st.session_state.answered = True
                    st.session_state.is_correct = is_correct
                    st.rerun()
    else:
        # 解答後の結果発表画面
        if st.session_state.is_correct:
            show_correct_animation()
            st.success("だいせいかい！🎉 1えん ゲット！")
        else:
            st.error(f"ざんねん… せいかいは 「{q['correct_answer']}」 でした！")
        
        # 次の問題へ進むボタン
        if st.button("つぎの もんだいへ！", type="primary"):
            del st.session_state.current_question
            del st.session_state.answered
            st.rerun()

def render_dad_dashboard():
    """パパ用 管理画面"""
    st.title("👨 パパ用 管理ダッシュボード")
    st.metric(label="未精算のお小遣い残高", value=f"{calculate_unpaid_allowance()} 円")
    
    if st.button("お小遣いを精算する（支払い完了）", type="primary"):
        execute_cash_out()
        st.success("精算処理が完了しました。")
        st.rerun()
        
    st.divider()
    st.subheader("問題の自動生成・ストック")
    
    # 現在のストック数を確認
    response = supabase.table("questions").select("*", count="exact").eq("is_used", False).execute()
    stock_count = response.count if response.count else 0
    st.write(f"現在の残りストック: {stock_count}問")
    
    # 手動で1問生成するフォーム
    with st.form("gen_form"):
        theme = st.text_input("テーマ（例：家族でスキー旅行）", "サイゼリヤで食事")
        word = st.text_input("ターゲット単語（例：snow）", "pizza")
        if st.form_submit_button("AIで問題を1問生成する"):
            with st.spinner("AIが水彩画と問題を作成中...（約10秒かかります）"):
                generate_and_stock_question(theme, word)
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