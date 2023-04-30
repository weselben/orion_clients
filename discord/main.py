import asyncio

import openai, discord, os, dotenv, mysql.connector, time
from discord.ext import commands

dotenv.load_dotenv()

openai.api_key = os.getenv('OPENAI_API_KEY')
database_host = "mariadb"
creator = "weselben#2929"
system_instructions = f"Be a helpfully AI, named OrionAI, you where created by {creator}!"

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)


def create_database():
    db = mysql.connector.connect(
        host=database_host,
        user="root",
        password=os.getenv('MYSQL_ROOT_PASSWORD')
    )
    cursor = db.cursor()
    cursor.execute("CREATE DATABASE IF NOT EXISTS discord_data")
    cursor.execute("USE discord_data")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INT AUTO_INCREMENT PRIMARY KEY,
            channel_id VARCHAR(255) NOT NULL,
            message_content TEXT NOT NULL,
            role TEXT NOT NULL,
            unixtimestamp INT NOT NULL
        )
    """)
    db.commit()
    print("Database and table created.")


def save_to_database(channel_id, message_content, role, timestamp):
    db = mysql.connector.connect(
        host=database_host,
        user="root",
        password=os.getenv('MYSQL_ROOT_PASSWORD'),
        database="discord_data"
    )
    cursor = db.cursor()
    sql = "INSERT INTO messages (channel_id, message_content, role, unixtimestamp) VALUES (%s, %s, %s, %s)"
    values = (channel_id, message_content, role, timestamp)
    cursor.execute(sql, values)
    db.commit()
    print("Data saved to database.")


def openai_proxy(messages):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=messages,
    )

    return response['choices'][0]['message']['content']


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")
    create_database()


def get_context_from_db(channel_id, current_time):
    db = mysql.connector.connect(
        host=database_host,
        user="root",
        password=os.getenv('MYSQL_ROOT_PASSWORD'),
        database="discord_data"
    )
    cursor = db.cursor()
    sql = "SELECT message_content FROM messages WHERE channel_id = %s AND unixtimestamp < %s ORDER BY unixtimestamp DESC LIMIT 10"
    values = (channel_id, current_time)
    cursor.execute(sql, values)
    results = cursor.fetchall()[::-1]  # Reverse the order of the results list
    messages = [
        {"role": "system", "content": system_instructions}]  # Add the system message at the beginning of the list
    for i, result in enumerate(results):
        if i % 2 == 0:
            role = "user"
        else:
            role = "assistant"
        messages.append({"role": role, "content": result[0]})
    return messages


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    elif isinstance(message.channel, discord.DMChannel):
        async with message.typing():
            channel_id = str(message.channel.id)
            message_content = message.content
            timestamp_received = int(time.time())
            messages = get_context_from_db(channel_id, time.time())
            if messages is None:
                messages = {"role": "system", "content": system_instructions}, {"role": "user",
                                                                                "content": message_content}
            else:
                messages.append({"role": "user", "content": message_content})
            print(messages)
            response = openai_proxy(messages)

            if len(response) <= int(2000):
                await message.reply(response, mention_author=False)
            elif len(response) >= int(2000):

                # Define the maximum length of each message part
                max_length = 2000

                # Split the response string into multiple message parts
                message_parts = []

                # Iterate over the indices of the response string in chunks of max_length
                for i in range(0, len(response), max_length):

                    # Get the current chunk of the response string
                    chunk = response[i:i + max_length]

                    # Check if the last character of the chunk is a space
                    if chunk[-1] == ' ':

                        # If it is, add the entire chunk to the message parts list
                        message_parts.append(chunk)

                    else:

                        # If not, find the last space character in the chunk
                        last_space = chunk.rfind(' ')

                        # If there is a space character in the chunk, split the chunk at that position
                        if last_space != -1:
                            message_parts.append(chunk[:last_space])
                            i -= (max_length - last_space)
                        else:
                            message_parts.append(chunk)

                # The resulting message parts list contains strings that are no longer than max_length characters.

                i = 0
                for part in message_parts:
                    if i == 1:
                        await asyncio.sleep(1)
                    await message.reply(part, mention_author=False)
                    i = 1
            else:
                try:
                    await message.reply(response, mention_author=False)
                except Exception as e:
                    await message.reply(f"Error: {e}")

            timestamp_sent = int(time.time())
            save_to_database(channel_id, message_content, "user", timestamp_received)
            save_to_database(channel_id, response, "assistant", timestamp_sent)
        return


bot.run(os.getenv('DISCORD_API_KEY'))
