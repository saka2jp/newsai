import json
import os
from datetime import datetime, timedelta
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from typing import Dict, List, Any
import argparse
from dotenv import load_dotenv
import time

load_dotenv()

class SlackMessageCollector:
    def __init__(self, token: str):
        self.client = WebClient(token=token)
        self.messages = []
        self.excluded_channels = self.get_excluded_channels()
        self.users = {}

    def get_users(self) -> Dict[str, Dict]:
        if self.users:
            return self.users
        try:
            print("👥 ユーザー一覧を取得中...")
            response = self.client.users_list(limit=200)
            members = response.get('members', [])
            while response.get('response_metadata', {}).get('next_cursor'):
                cursor = response['response_metadata']['next_cursor']
                time.sleep(0.3)
                response = self.client.users_list(limit=200, cursor=cursor)
                members.extend(response.get('members', []))
            for member in members:
                if member.get('is_bot') or member.get('id') == 'USLACKBOT':
                    continue
                user_id = member.get('id')
                self.users[user_id] = {
                    'id': user_id,
                    'name': member.get('name', ''),
                    'real_name': member.get('real_name', member.get('name', '')),
                    'display_name': member.get('profile', {}).get('display_name', '')
                }
            print(f"✅ {len(self.users)} ユーザーを取得")
            return self.users
        except SlackApiError as e:
            print(f"❌ ユーザー取得エラー: {e.response.get('error', '')}")
            return {}

    def get_excluded_channels(self) -> List[str]:
        excluded = []
        exclude_raw = os.environ.get("SLACK_EXCLUDE_CHANNELS", "")
        if exclude_raw:
            excluded.extend(exclude_raw.split(","))
        post_channel = os.environ.get("SLACK_CHANNEL", "")
        if post_channel and post_channel not in excluded:
            excluded.append(post_channel)
        return excluded
        
    def get_bot_info(self) -> Dict:
        """ボットの情報を取得"""
        try:
            response = self.client.auth_test()
            return {
                'bot_id': response.get('user_id'),
                'bot_name': response.get('user'),
                'team': response.get('team')
            }
        except SlackApiError as e:
            print(f"ボット情報の取得に失敗: {e.response['error']}")
            return {}
    
    def join_channel(self, channel_id: str, channel_name: str) -> bool:
        """チャンネルに参加"""
        if channel_name.lower() in self.excluded_channels:
            print(f"  ⏭️ #{channel_name} は除外設定のためスキップ")
            return False

        try:
            self.client.conversations_join(channel=channel_id)
            print(f"  ✅ #{channel_name} に参加しました")
            time.sleep(0.5)  # API制限を考慮
            return True
        except SlackApiError as e:
            error = e.response.get('error', '')
            if error == 'already_in_channel':
                return True
            elif error == 'is_archived':
                print(f"  ⚠️  #{channel_name} はアーカイブ済み")
            elif error == 'is_private':
                print(f"  🔒 #{channel_name} はプライベート（招待が必要）")
            else:
                print(f"  ❌ #{channel_name} 参加失敗: {error}")
            return False
            
    def get_channel_messages(self, channel_id: str, channel_name: str, oldest_timestamp: str) -> List[Dict]:
        """特定チャンネルのメッセージを取得"""
        all_messages = []
        if channel_name in self.excluded_channels:
            print(f"  ⏭️ #{channel_name} は除外設定のためスキップ")
            return []

        try:
            print(f"  📥 #{channel_name} のメッセージを取得中...")
            
            # 最初のバッチを取得
            response = self.client.conversations_history(
                channel=channel_id,
                oldest=oldest_timestamp,
                limit=200  # より小さなバッチサイズ
            )
            
            messages = response.get('messages', [])
            
            for msg in messages:
                msg['channel_id'] = channel_id
                msg['channel_name'] = channel_name
                msg['timestamp_formatted'] = datetime.fromtimestamp(float(msg.get('ts', 0))).isoformat()
                user_id = msg.get('user', '')
                if user_id and user_id in self.users:
                    msg['user_name'] = self.users[user_id].get('real_name', '')
            
            all_messages.extend(messages)
            
            # ページネーション処理
            while response.get('has_more', False):
                cursor = response.get('response_metadata', {}).get('next_cursor')
                if not cursor:
                    break
                
                time.sleep(0.3)  # API制限対策
                
                response = self.client.conversations_history(
                    channel=channel_id,
                    oldest=oldest_timestamp,
                    cursor=cursor,
                    limit=200
                )
                
                messages = response.get('messages', [])
                for msg in messages:
                    msg['channel_id'] = channel_id
                    msg['channel_name'] = channel_name
                    msg['timestamp_formatted'] = datetime.fromtimestamp(float(msg.get('ts', 0))).isoformat()
                    user_id = msg.get('user', '')
                    if user_id and user_id in self.users:
                        msg['user_name'] = self.users[user_id].get('real_name', '')
                all_messages.extend(messages)
            
            if all_messages:
                print(f"     ✅ {len(all_messages)} メッセージを取得")
            else:
                print(f"     ℹ️  メッセージなし")
                
            return all_messages
            
        except SlackApiError as e:
            error = e.response.get('error', '')
            if error == 'not_in_channel':
                print(f"     ❌ チャンネルのメンバーではありません")
            elif error == 'missing_scope':
                print(f"     ❌ 権限不足: channels:history または groups:history スコープが必要")
            else:
                print(f"     ❌ エラー: {error}")
            return []
    
    def collect_messages(self, days: int = 7, auto_join: bool = True, channel_filter: str = None) -> Dict[str, Any]:
        """メッセージを収集"""
        
        print(f"\n{'='*60}")
        print(f"📊 Slack メッセージ収集を開始（過去{days}日間）")
        print(f"{'='*60}\n")
        
        self.get_users()
        
        bot_info = self.get_bot_info()
        if bot_info:
            print(f"🤖 ボット: {bot_info['bot_name']} ({bot_info['team']})")
        
        # 期間設定
        now = datetime.now()
        past = now - timedelta(days=days)
        oldest_timestamp = str(past.timestamp())
        
        collection_info = {
            'timestamp': now.isoformat(),
            'period': {
                'from': past.isoformat(),
                'to': now.isoformat(),
                'days': days
            },
            'bot_info': bot_info
        }
        
        # チャンネル一覧を取得
        try:
            print("\n📋 チャンネル一覧を取得中...")
            
            # パブリックチャンネルとプライベートチャンネルを取得
            response = self.client.conversations_list(
                exclude_archived=True,
                types="public_channel,private_channel",
                limit=100
            )
            
            channels = response.get('channels', [])
            
            # ページネーション
            while response.get('response_metadata', {}).get('next_cursor'):
                cursor = response['response_metadata']['next_cursor']
                response = self.client.conversations_list(
                    exclude_archived=True,
                    types="public_channel,private_channel",
                    limit=100,
                    cursor=cursor
                )
                channels.extend(response.get('channels', []))
            
            print(f"✅ {len(channels)} チャンネルを発見\n")
            
        except SlackApiError as e:
            print(f"❌ チャンネル取得エラー: {e.response['error']}")
            return {'messages': [], 'info': collection_info, 'error': str(e)}
        
        # 各チャンネルからメッセージを収集
        all_messages = []
        channels_processed = 0
        channels_with_messages = 0
        
        print("📬 メッセージ収集中...\n")
        
        for channel in channels:
            channel_id = channel['id']
            channel_name = channel.get('name', 'unnamed')
            is_private = channel.get('is_private', False)
            is_member = channel.get('is_member', False)
            
            # フィルタリング
            if channel_filter and channel_filter not in channel_name:
                continue
            
            print(f"{'🔒' if is_private else '📢'} #{channel_name}")
            
            # メンバーでない場合
            if not is_member:
                if auto_join and not is_private:
                    # パブリックチャンネルに自動参加
                    if self.join_channel(channel_id, channel_name):
                        is_member = True
                else:
                    if is_private:
                        print(f"  🔒 プライベートチャンネル（スキップ）")
                    else:
                        print(f"  ⏭️  未参加（自動参加無効）")
                    continue
            
            # メッセージを取得
            if is_member:
                messages = self.get_channel_messages(channel_id, channel_name, oldest_timestamp)
                if messages:
                    all_messages.extend(messages)
                    channels_with_messages += 1
                channels_processed += 1
            
            # API制限対策
            time.sleep(0.2)
        
        # 結果をまとめる
        self.messages = all_messages
        
        # タイムスタンプでソート（新しい順）
        self.messages.sort(key=lambda x: x.get('ts', ''), reverse=True)
        
        print(f"\n{'='*60}")
        print("📊 収集完了サマリー")
        print(f"{'='*60}")
        print(f"✅ 処理チャンネル数: {channels_processed}")
        print(f"💬 メッセージ取得チャンネル数: {channels_with_messages}")
        print(f"📝 総メッセージ数: {len(self.messages)}")
        print(f"📅 期間: {past.strftime('%Y-%m-%d')} 〜 {now.strftime('%Y-%m-%d')}")
        print(f"{'='*60}\n")
        
        return {
            'messages': self.messages,
            'info': collection_info,
            'statistics': {
                'total_messages': len(self.messages),
                'channels_processed': channels_processed,
                'channels_with_messages': channels_with_messages
            },
            'users': self.users
        }
    
    def save_messages(self, filename: str = None) -> str:
        """メッセージをファイルに保存"""
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"slack_messages_{timestamp}.json"
        
        data = {
            'messages': self.messages,
            'total_count': len(self.messages),
            'exported_at': datetime.now().isoformat()
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"💾 {filename} に保存しました（{len(self.messages)} メッセージ）")
        return filename

def main():
    parser = argparse.ArgumentParser(
        description='Slack メッセージ収集ツール',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python collect_slack_messages.py                    # 過去7日間のメッセージを収集
  python collect_slack_messages.py --days 30         # 過去30日間のメッセージを収集
  python collect_slack_messages.py --channel general # generalを含むチャンネルのみ
  python collect_slack_messages.py --no-auto-join    # 自動参加を無効化
        """
    )
    
    parser.add_argument('--days', type=int, default=7, help='収集する日数（デフォルト: 7日）')
    parser.add_argument('--output', type=str, help='出力ファイル名')
    parser.add_argument('--token', type=str, help='Slackボットトークン（環境変数より優先）')
    parser.add_argument('--no-auto-join', action='store_true', help='チャンネルへの自動参加を無効にする')
    parser.add_argument('--channel', type=str, help='特定のチャンネル名を含むものだけを対象にする')
    
    args = parser.parse_args()
    
    # トークン取得
    slack_token = args.token or os.environ.get('SLACK_BOT_TOKEN')
    
    if not slack_token:
        print("❌ エラー: SLACK_BOT_TOKEN が設定されていません")
        print("\n以下のいずれかの方法でトークンを設定してください:")
        print("1. 環境変数: export SLACK_BOT_TOKEN='xoxb-...'")
        print("2. .envファイル: SLACK_BOT_TOKEN=xoxb-...")
        print("3. コマンドライン: --token xoxb-...")
        return 1
    
    # コレクター初期化
    collector = SlackMessageCollector(slack_token)
    
    try:
        # メッセージ収集
        result = collector.collect_messages(
            days=args.days,
            auto_join=not args.no_auto_join,
            channel_filter=args.channel
        )
        
        # ファイルに保存
        if result['messages']:
            filename = collector.save_messages(args.output)
            
            # 簡易プレビュー
            print("\n📄 メッセージプレビュー（最新5件）:")
            print("-" * 60)
            for msg in result['messages'][:5]:
                timestamp = msg.get('timestamp_formatted', '')
                channel = msg.get('channel_name', 'unknown')
                text = msg.get('text', '')[:100]
                if text:
                    print(f"[{timestamp[:10]}] #{channel}: {text}")
            
            return 0
        else:
            print("\n⚠️ メッセージが見つかりませんでした")
            print("\n考えられる原因:")
            print("1. ボットがチャンネルのメンバーでない")
            print("2. 指定期間内にメッセージがない")
            print("3. 必要な権限（channels:history, groups:history）がない")
            return 1
            
    except Exception as e:
        print(f"\n❌ 予期しないエラー: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())
