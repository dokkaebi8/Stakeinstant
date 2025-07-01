from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import logging

# ロギング設定（コンソール出力のみ）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

# Chrome用オプション設定
options = Options()
# ※各自の環境に合わせ、ユーザーデータディレクトリのパスを変更してください
options.add_argument('user-data-dir=/path/to/your/custom/profile')
options.add_experimental_option("detach", True)
options.page_load_strategy = 'eager'

# Chromeドライバーの起動
driver = webdriver.Chrome(options=options)
driver.implicitly_wait(1)

# ページ内の指定XPathのコンテナから動画要素を監視し、
# 動画の最終フレームを抽出・保存するJavaScriptコードを注入する関数
def inject_video_monitor_js():
    js_code = r'''
    (async function continuouslyMonitorVideos() {
      // ① 指定XPathから対象コンテナを取得する
      const containerXPath = '/html/body/div[2]/div/div[4]/div/div';
      function getContainer() {
        const result = document.evaluate(
          containerXPath,
          document,
          null,
          XPathResult.FIRST_ORDERED_NODE_TYPE,
          null
        );
        return result.singleNodeValue;
      }
      
      let container = getContainer();
      if (!container) {
        console.error("指定されたXPathのコンテナが見つかりません。");
        return;
      }
      
      // ② 新たな動画要素を処理するためのキュー
      const videoQueue = [];
      let isProcessing = false;
      
      // ③ 待機用のPromiseラッパー
      function delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
      }
      
      // ④ 1件の動画要素について、最終フレームを抽出して保存する処理
      async function processVideoElement(video) {
        // 動画要素のsrc属性からユニークなキーを取得（"stream/"で始まる場合、JSONデータからaccess_hashを抽出）
        const src = video.getAttribute("src");
        if (!src) return;
        let uniqueKey = src;
        if (src.startsWith("stream/")) {
          const encoded = src.substring("stream/".length);
          try {
            const decoded = decodeURIComponent(encoded);
            const obj = JSON.parse(decoded);
            if (obj.location && obj.location.access_hash) {
              uniqueKey = obj.location.access_hash;
            }
          } catch (e) {
            console.error("srcのJSONパースに失敗:", src, e);
          }
        }
        
        // 既に処理済みならスキップ（ローカルストレージで重複チェック）
        if (localStorage.getItem("processed_video_" + uniqueKey)) {
          console.log("動画（キー:" + uniqueKey + "）はすでに処理済みです。");
          return;
        }
        
        // 一応動画再生を停止
        video.pause();
        
        // 動画の再生位置を最後（duration）に設定し、最終フレームをCanvasでキャプチャ
        await new Promise((resolve, reject) => {
          function startExtraction() {
            video.currentTime = video.duration;
            video.addEventListener('seeked', function onSeeked() {
              video.removeEventListener('seeked', onSeeked);
              const canvas = document.createElement('canvas');
              canvas.width = video.videoWidth;
              canvas.height = video.videoHeight;
              const ctx = canvas.getContext('2d');
              ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
              canvas.toBlob((blob) => {
                if (!blob) {
                  reject("Blobの生成に失敗しました。");
                  return;
                }
                const blobUrl = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.download = 'final_frame_' + uniqueKey + '.png';
                a.href = blobUrl;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(blobUrl);
                console.log("動画の最終フレームを保存しました。キー:", uniqueKey);
                resolve();
              }, 'image/png');
            }, { once: true });
          }
          if (video.readyState >= 2) {
            startExtraction();
          } else {
            video.addEventListener('loadeddata', () => {
              startExtraction();
            }, { once: true });
          }
        }).catch(err => {
          console.error("動画処理中のエラー:", err);
        });
        
        // 重複防止のため、ローカルストレージへ保存（タイムスタンプ付き）
        localStorage.setItem("processed_video_" + uniqueKey, Date.now());
      }
      
      // ⑤ キュー内の動画を順次処理（各動画処理後、3秒待機）
      async function processQueue() {
        if (isProcessing) return;
        isProcessing = true;
        while (true) {
          if (videoQueue.length > 0) {
            const video = videoQueue.shift();
            await processVideoElement(video);
            await delay(3000);
          } else {
            // キューが空の場合は1秒待って再チェック
            await delay(1000);
          }
        }
      }
      
      // ⑥ MutationObserverで、コンテナに追加される新動画要素を監視する
      const observer = new MutationObserver(mutations => {
        mutations.forEach(mutation => {
          mutation.addedNodes.forEach(node => {
            if (node.nodeType === Node.ELEMENT_NODE) {
              // 追加ノード自体がvideo要素の場合
              if (node.tagName.toLowerCase() === "video") {
                const src = node.getAttribute("src");
                if (src) {
                  let uniqueKey = src;
                  if (src.startsWith("stream/")) {
                    const encoded = src.substring("stream/".length);
                    try {
                      const decoded = decodeURIComponent(encoded);
                      const obj = JSON.parse(decoded);
                      if (obj.location && obj.location.access_hash) {
                        uniqueKey = obj.location.access_hash;
                      }
                    } catch (e) {
                      console.error("追加された動画のJSONパース失敗", e);
                    }
                  }
                  if (!localStorage.getItem("processed_video_" + uniqueKey)) {
                    videoQueue.push(node);
                  }
                }
              } else {
                // 追加ノード内に子孫としてvideo要素が存在する場合
                const videosInNode = node.querySelectorAll && node.querySelectorAll("video");
                if (videosInNode && videosInNode.length) {
                  videosInNode.forEach(v => {
                    const src = v.getAttribute("src");
                    if (src) {
                      let uniqueKey = src;
                      if (src.startsWith("stream/")) {
                        const encoded = src.substring("stream/".length);
                        try {
                          const decoded = decodeURIComponent(encoded);
                          const obj = JSON.parse(decoded);
                          if (obj.location && obj.location.access_hash) {
                            uniqueKey = obj.location.access_hash;
                          }
                        } catch (e) {
                          console.error("追加された動画（子孫）のJSONパース失敗", e);
                        }
                      }
                      if (!localStorage.getItem("processed_video_" + uniqueKey)) {
                        videoQueue.push(v);
                      }
                    }
                  });
                }
              }
            }
          });
        });
      });
      
      observer.observe(container, { childList: true, subtree: true });
      
      // ⑦ 初回時点でコンテナ内の未処理のvideo要素をキューに追加
      container.querySelectorAll("video").forEach(video => {
        const src = video.getAttribute("src");
        if (src) {
          let uniqueKey = src;
          if (src.startsWith("stream/")) {
            const encoded = src.substring("stream/".length);
            try {
              const decoded = decodeURIComponent(encoded);
              const obj = JSON.parse(decoded);
              if (obj.location && obj.location.access_hash) {
                uniqueKey = obj.location.access_hash;
              }
            } catch (e) {
              console.error("初期動画のJSONパース失敗", e);
            }
          }
          if (!localStorage.getItem("processed_video_" + uniqueKey)) {
            videoQueue.push(video);
          }
        }
      });
      
      console.log("動画監視を開始します。新しい動画が到着したら自動処理されます。");
      processQueue();
    })();
    '''
    try:
        driver.execute_script(js_code)
        logging.info("動画監視用JSコードを正常に注入しました。")
    except Exception as e:
        logging.error(f"動画監視JSコードの注入中に例外が発生しました: {e}")

try:
    print("動画監視を開始します...")
    # ※必要に応じて表示したいページのURLに変更してください
    driver.get('https://web.telegram.org/k/#@StakecomDailyDrops')
    
    # ページ全体が読み込まれるまで待機
    WebDriverWait(driver, 5).until(
        lambda d: d.execute_script('return document.readyState') == 'complete'
    )
    logging.info("ページの読み込みが完了しました。")
    
    # ページに動画監視用JSコードを注入
    inject_video_monitor_js()
    
    logging.info("動画監視処理を実行中です。ブラウザは開いたままになります。")
    
    # メインスレッドを無限ループで待機（JS側の監視処理を継続させる）
    while True:
        time.sleep(1)
        
except Exception as ex:
    logging.error(f"例外が発生しました: {ex}")
    
finally:
    driver.quit()
