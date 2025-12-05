import os
from dotenv import load_dotenv
from collect_slack_messages import SlackMessageCollector
from generate_weekly_news import WeeklyNewsGenerator
from post_slack import SlackPoster


def main() -> int:
    load_dotenv()
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    openai_key = os.environ.get("OPENAI_API_KEY")
    slack_channel = os.environ.get("SLACK_CHANNEL")

    if not slack_token:
        print("❌ エラー: SLACK_BOT_TOKEN が設定されていません")
        return 1
    if not openai_key:
        print("❌ エラー: OPENAI_API_KEY が設定されていません")
        return 1
    if not slack_channel:
        print("❌ エラー: SLACK_CHANNEL が設定されていません。投稿先チャンネルを環境変数で指定してください")
        return 1

    print("📥 1週間分のSlackメッセージを取得します...")
    collector = SlackMessageCollector(slack_token)
    result = collector.collect_messages(days=7, auto_join=True)
    messages = result.get("messages", [])
    users = result.get("users", {})
    if not messages:
        print("⚠️ メッセージが取得できませんでした")
        return 1

    print("🧠 今週の話題ニュースを生成します...")
    generator = WeeklyNewsGenerator(openai_key)
    summary = generator.generate_news_text(days=7, messages=messages, users=users)
    if not summary:
        print("❌ 要約の生成に失敗しました")
        return 1

    print("📤 Slackに投稿します...")
    poster = SlackPoster(token=slack_token, default_channel=slack_channel)
    poster.post(text=summary, channel=slack_channel, thread=True)
    return 0


if __name__ == "__main__":
    exit(main())


