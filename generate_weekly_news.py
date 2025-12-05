import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any
import argparse
from dotenv import load_dotenv
from openai import OpenAI
import re

load_dotenv()

class WeeklyNewsGenerator:
    def __init__(self, openai_api_key: str):
        self.openai_client = OpenAI(api_key=openai_api_key)
        self.users = {}
        
    def load_messages(self, filename: str) -> List[Dict]:
        """保存されたメッセージファイルを読み込む"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
                messages = data.get('messages', [])
                print(f"📥 {len(messages)} 件のメッセージを読み込みました")
                return messages
        except FileNotFoundError:
            print(f"❌ ファイルが見つかりません: {filename}")
            return []
        except json.JSONDecodeError:
            print(f"❌ JSONファイルの読み込みエラー: {filename}")
            return []
    
    def filter_recent_messages(self, messages: List[Dict], days: int = 7) -> List[Dict]:
        """指定日数以内のメッセージをフィルタリング"""
        cutoff_time = (datetime.now() - timedelta(days=days)).timestamp()
        recent_messages = []
        
        for msg in messages:
            try:
                msg_ts = float(msg.get('ts', 0))
                if msg_ts >= cutoff_time:
                    recent_messages.append(msg)
            except (ValueError, TypeError):
                continue
        
        print(f"📅 過去{days}日間のメッセージ: {len(recent_messages)}件")
        return recent_messages
    
    def prepare_messages_for_analysis(self, messages: List[Dict]) -> str:
        """メッセージを分析用に整形"""
        formatted_messages = []
        
        # チャンネルごとにグループ化
        channels = {}
        for msg in messages:
            channel = msg.get('channel_name', 'unknown')
            if channel not in channels:
                channels[channel] = []
            
            # ボットメッセージや添付ファイルのみのメッセージはスキップ
            if msg.get('subtype') in ['bot_message', 'file_share']:
                continue
                
            text = msg.get('text', '').strip()
            if not text or len(text) < 10:  # 短すぎるメッセージはスキップ
                continue
                
            # URL削除
            text = re.sub(r'<https?://[^\s>]+>', '', text)
            text = re.sub(r'https?://[^\s]+', '', text)
            
            # メンション削除
            text = re.sub(r'<@[A-Z0-9]+>', '', text)
            
            # 絵文字削除（簡易版）
            text = re.sub(r':[a-z_]+:', '', text)
            
            # 改行削除
            text = re.sub(r'\n', '', text)
            
            user_name = msg.get('user_name', '')
            channels[channel].append({
                'text': text[:500],
                'user_name': user_name
            })
        
        for channel, msgs in channels.items():
            if msgs:
                formatted_messages.append(f"\n#チャンネル：【#{channel}】")
                for msg in msgs[-100:]:
                    user_part = f"[{msg['user_name']}] " if msg.get('user_name') else ""
                    formatted_messages.append(f"- {user_part}{msg['text']}")
        
        return "\n".join(formatted_messages)

    def prepare_users_for_analysis(self) -> str:
        if not self.users:
            return ""
        user_list = []
        for user_id, user_info in self.users.items():
            real_name = user_info.get('real_name', '')
            if real_name:
                user_list.append(f"- {real_name}: <@{user_id}>")
        return "\n".join(user_list)
    
    def generate_news_summary(self, messages_text: str) -> str:
        print("🤖 OpenAI APIで分析中...")
        
        users_text = self.prepare_users_for_analysis()
        
        try:
            prompt = """#指示
以下のSlackメッセージから、「話題のニュース」として取り上げるのに良さそうなものをピックアップして「今週の注目ニュース」として取り上げるのにふさわしいものをピックアップしてください。

- 上位10件の「今週の注目ニュース」を選んでください。
- 外部のニュースは取り上げないでください。
- もし重要なニュースが見つからない場合は、「今週は特に重要なニュースはありませんでした」と返してください。
- ネガティブなニュースは取り上げないでください。
- 番外編として、ユーモアのあるニュースを5件選んでください。
- 出力結果には【注目ニュース】と【番外編】の2つのセクションを作成してください。
- 出力結果には枕詞や最後のコメントは含めないでください。
- 各ニュースに関連するメンバーを推論してください。メッセージの投稿者だけでなく、メッセージ内容から関連すると推論される人を含めてください。関連度が高い順に最大5人まで選んでください。

#出力形式
- 各ニュースの間には必ず空行を1行入れてください。
- ニュースタイトル。タイトルの先頭にニュースの番号を付けてください。ニュースの最後にはタイトルに対応する絵文字を付けてください。ニュースタイトルは*で囲んでください。
- 詳細説明（1-2文）。200字以内程度。
- 関連チャンネルと関連メンバーは1行にまとめて括弧内にコンパクトに記載してください。関連メンバーはユーザー一覧のメンション形式（<@USER_ID>）をそのまま使用してください。

例：
【注目ニュース】

1. *ニュースタイトル* 絵文字
詳細説明をここに記載します。
（ #channel_name / 関連: <@U12345678>, <@U87654321>）

2. *次のニュースタイトル* 絵文字
詳細説明をここに記載します。
（ #channel_name / 関連: <@U12345678>）

【番外編】

1. *ニュースタイトル* 絵文字
詳細説明をここに記載します。
（ #channel_name / 関連: <@U12345678>）

#ユーザー一覧
以下は社内のユーザー一覧です。名前とメンション形式の対応を示しています。関連メンバーを出力する際は、必ずこの一覧にあるメンション形式を使用してください。
""" + users_text + """

#Slackメッセージ
Slackメッセージはある会社内でやり取りされた1週間分のメッセージです。各メッセージには投稿者名が[名前]の形式で含まれています。
"""
            
            response = self.openai_client.chat.completions.create(
                model="gpt-5",
                messages=[
                    {"role": "system", "content": "あなたは社内コミュニケーションの専門家です。Slackメッセージから重要な情報を抽出し、わかりやすくまとめることが得意です。"},
                    {"role": "user", "content": prompt + messages_text}
                ],
                max_completion_tokens=15000
            )
            
            summary = response.choices[0].message.content
            print("✅ ニュースサマリー生成完了")
            return summary
            
        except Exception as e:
            print(f"❌ OpenAI APIエラー: {str(e)}")
            return None
    

    
    def generate_news_text(self, messages_file: str = None, days: int = 7, messages: List[Dict] = None, users: Dict = None) -> str:
        print(f"\n{'='*60}")
        print(f"📰 週次ニュース生成を開始")
        print(f"{'='*60}\n")
        
        if users:
            self.users = users
        
        if messages is None:
            if not messages_file:
                print("❌ メッセージソースが指定されていません")
                return None
            messages = self.load_messages(messages_file)
            if not messages:
                print("❌ メッセージが読み込めませんでした")
                return None
        
        # 最近のメッセージをフィルタリング
        recent_messages = self.filter_recent_messages(messages, days)
        if not recent_messages:
            print("❌ 対象期間のメッセージがありません")
            return None
        
        # 分析用にメッセージを整形
        formatted_text = self.prepare_messages_for_analysis(recent_messages)
        if not formatted_text:
            print("❌ 分析可能なメッセージがありません")
            return None
        
        print(f"📝 分析対象: {len(formatted_text)} 文字")
        
        # ニュースサマリーを生成
        summary = self.generate_news_summary(formatted_text)
        if not summary:
            print("❌ ニュースサマリーの生成に失敗しました")
            return None
        
        print("\n" + "="*60)
        print("📋 生成されたニュースサマリー:")
        print("="*60)
        print(summary)
        print("="*60 + "\n")
        
        return summary

def main():
    parser = argparse.ArgumentParser(
        description='週次社内ニュース生成ツール',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python generate_weekly_news.py
  python generate_weekly_news.py --days 7
  python generate_weekly_news.py --messages-file slack_messages_20250928.json
        """
    )
    
    parser.add_argument('--messages-file', type=str, help='メッセージファイルのパス（デフォルト: 最新のslack_messages_*.json）')
    parser.add_argument('--days', type=int, default=7, help='分析対象の日数（デフォルト: 7日）')
    parser.add_argument('--openai-key', type=str, help='OpenAI APIキー（環境変数より優先）')
    
    args = parser.parse_args()
    
    # APIキー取得
    openai_key = args.openai_key or os.environ.get('OPENAI_API_KEY')
    
    if not openai_key:
        print("❌ エラー: OPENAI_API_KEY が設定されていません")
        print("\n環境変数を設定してください:")
        print("export OPENAI_API_KEY='sk-...'")
        return 1
    
    # メッセージファイルを自動検出
    if not args.messages_file:
        import glob
        json_files = glob.glob("slack_messages_*.json")
        if json_files:
            args.messages_file = sorted(json_files)[-1]  # 最新のファイル
            print(f"📁 メッセージファイル: {args.messages_file}")
        else:
            print("❌ slack_messages_*.json ファイルが見つかりません")
            print("先に collect_slack_messages.py を実行してください")
            return 1
    
    # ジェネレーター初期化
    generator = WeeklyNewsGenerator(openai_key)
    
    try:
        # ニューステキスト生成
        news_text = generator.generate_news_text(
            messages_file=args.messages_file,
            days=args.days
        )
        
        if news_text:
            print("\n✅ ニューステキストの生成が完了しました")
            print(news_text)
            return 0
        else:
            print("\n❌ ニューステキストの生成に失敗しました")
            return 1
            
    except Exception as e:
        print(f"\n❌ 予期しないエラー: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())
