from mitmproxy import http
from PIL import Image
import io
import chardet
import re

def request(flow: http.HTTPFlow):
    # 1. 偽装するUA
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"

    # 2. CFが期待する「標準的なヘッダーとその順序」で再構成
    # OASYSからの古いヘッダーを一度捨て、真っさらな状態から組み立てる
    new_headers = http.Headers()
    new_headers["Host"] = flow.request.host
    new_headers["Connection"] = "keep-alive"
    new_headers["Upgrade-Insecure-Requests"] = "1"
    new_headers["User-Agent"] = ua
    new_headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    new_headers["Accept-Language"] = "ja,en-US;q=0.9,en;q=0.8"
    new_headers["Accept-Encoding"] = "gzip, deflate" # OASYSが対応してなければmitmproxyが解凍してくれる

    # Cookieがあれば引き継ぐ
    if "Cookie" in flow.request.headers:
        new_headers["Cookie"] = flow.request.headers["Cookie"]

    # 3. 古いヘッダーを全置換
    flow.request.headers = new_headers

    # 4. Content-Lengthの修正
    if flow.request.content:
        flow.request.headers["Content-Length"] = str(len(flow.request.content))

def response(flow: http.HTTPFlow):
    # 圧縮解除
    flow.response.decode()

    # 1. 【画像処理】
    if "image" in flow.response.headers.get("Content-Type", ""):
        try:
            img = Image.open(io.BytesIO(flow.response.content))
            if img.mode != "RGB":
                img = img.convert("RGB")
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=60)
            flow.response.content = out.getvalue()
            flow.response.headers["Content-Type"] = "image/jpeg"
            flow.response.headers["Content-Length"] = str(len(flow.response.content))
        except:
            pass

    # 2. 【HTML・文字コード処理】
    if "text/html" in flow.response.headers.get("Content-Type", ""):
        try:
            content = flow.response.content
            det = chardet.detect(content)
            encoding = det['encoding'] or 'utf-8'
            text = content.decode(encoding, errors='replace')

            # --- 構造修復 ---
            # HTTPSリンクをすべてHTTPへ（OASYSの通信断絶を防ぐ）
            text = text.replace('https://', 'http://')

            # 既存の誤解を招くmetaタグを根こそぎ削除
            text = re.sub(r'<meta[^>]*charset=[^>]*>', '', text, flags=re.IGNORECASE)
            text = re.sub(r'<meta[^>]*http-equiv=["\']?content-type["\']?[^>]*>', '', text, flags=re.IGNORECASE)

            # OASYSが最も確実に認識する「おまじない」をHTMLの最先端に挿入
            # 文頭にこれがあることで、ブラウザが最初からShift_JISモードでパースを開始します
            omajinai = '<HTML><HEAD><META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=Shift_JIS"></HEAD><BODY>'

            # <html> や <body> が重複しないよう強引にクリーニング
            text = re.sub(r'<(html|head|body)[^>]*>', '', text, flags=re.IGNORECASE)
            text = omajinai + text + '</BODY></HTML>'

            # Shift_JIS(CP932)に変換
            flow.response.content = text.encode('cp932', errors='replace')

            # ヘッダーを固定
            flow.response.headers["Content-Type"] = "text/html; charset=shift-jis"
            flow.response.headers.pop("Content-Encoding", None)
            flow.response.headers["Content-Length"] = str(len(flow.response.content))

            # キャッシュを無効化して常に最新を読み込ませる（古いブラウザでの混乱防止）
            flow.response.headers["Cache-Control"] = "no-cache"

        except Exception as e:
            print(f"Conversion error: {e}")