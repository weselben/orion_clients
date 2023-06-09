import asyncio

import openai, discord, os, dotenv, mysql.connector, time, logging
from discord.ext import commands

dotenv.load_dotenv()

openai.api_key = os.getenv('OPENAI_API_KEY')
database_host = "mariadb"
database = "discord_data"
creator = "weselben#2929"
weselben_userid = "261636096276955136"
system_instructions = f"Your a helpful AI that can Chat through Discord. Your name is OrionAI. You where created by {creator} NOT by OpenAI. If u are asked something that u dont know behave like you know it and create a place holder like following <:str>"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s | %(message)s'
)

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
    cursor.execute("""
            CREATE TABLE IF NOT EXISTS config (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                image_gen_conf BOOLEAN NOT NULL DEFAULT FALSE
            )
        """)
    db.commit()
    logging.info("Database and table created.")


def save_to_database(channel_id, message_content, role, timestamp):
    db = mysql.connector.connect(
        host=database_host,
        user="root",
        password=os.getenv('MYSQL_ROOT_PASSWORD'),
        database=database
    )
    cursor = db.cursor()
    sql = "INSERT INTO messages (channel_id, message_content, role, unixtimestamp) VALUES (%s, %s, %s, %s)"
    values = (channel_id, message_content, role, timestamp)
    cursor.execute(sql, values)
    db.commit()
    logging.info("Data saved to database.")


def openai_proxy(messages):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=messages,
    )
    return_value = response['choices'][0]['message']['content']
    logging.info(f'{bot.user.name}:{return_value}')
    if "weselben" in return_value or "weselben#2929" in return_value:
        return_value = return_value.replace("weselben", f"<@{weselben_userid}>")
        return_value = return_value.replace("Weselben", f"<@{weselben_userid}>")
    return return_value


def openai_image_gen(message_content):
    logging.info("Image Generation Started")

    def interpret_text(content):
        # Set up the OpenAI API request parameters
        parameters = {

        }

        # Send a POST request to the OpenAI API
        response = openai.Completion.create(
            model='text-davinci-003',
            prompt=f"Extract the most relevant keywords from this text:\n\n{content}\n\nKeywords: ",
            temperature=0.5,
            max_tokens=60,
            top_p=1.0,
            frequency_penalty=0.8,
            presence_penalty=0.0
        )

        # Extract the generated text from the API response
        generated_text = response.choices[0].text.strip()[10:].strip()

        # Split the generated text by commas to get the keywords
        keywords = [word.strip() for word in generated_text.split(',')]

        return keywords

    def generate_images(keyword_list, size='1024x1024'):
        # Join the keywords into a prompt string
        prompt = '\n'.join([f"{index + 1}. {keyword}" for index, keyword in enumerate(keyword_list)])

        # Send a POST request to the OpenAI API
        response = openai.Image.create(
            prompt=prompt,
            n=1,
            size=size
        )
        url = response["data"][0]["url"]

        # Return the URL of the best image as a string
        return url

    return generate_images(interpret_text(message_content))


@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user.name} ({bot.user.id})")
    create_database()


def get_context_from_db(channel_id, current_time, limit=15):
    db = mysql.connector.connect(
        host=database_host,
        user="root",
        password=os.getenv('MYSQL_ROOT_PASSWORD'),
        database=database
    )
    cursor = db.cursor()
    sql = f"SELECT message_content FROM messages WHERE channel_id = %s AND unixtimestamp < %s ORDER BY unixtimestamp DESC LIMIT {int(limit)}"
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


def split_response(response):
    message_parts = []
    max_length = 2000
    while len(response) > max_length:
        idx = response.rfind(' ', 0, max_length)
        if idx == -1:
            # No space found, split at max_length
            message_parts.append(response[:max_length])
            response = response[max_length:]
        else:
            message_parts.append(response[:idx])
            response = response[idx + 1:]
    message_parts.append(response)
    return message_parts


def update_image_gen_conf(user_id, new_value):
    db = mysql.connector.connect(
        host=database_host,
        user="root",
        password=os.getenv('MYSQL_ROOT_PASSWORD'),
        database=database
    )
    cursor = db.cursor()

    sql = "INSERT INTO config (user_id, image_gen_conf) VALUES (%s, %s) ON DUPLICATE KEY UPDATE image_gen_conf = %s"
    values = (user_id, new_value, new_value)
    cursor.execute(sql, values)

    db.commit()

    info = f"Changed image_gen to '{new_value}'"
    logging.info(info)
    return info



def get_image_gen_conf(channel_id):
    # Establish a connection to the database
    db = mysql.connector.connect(
        host=database_host,
        user="root",
        password=os.getenv('MYSQL_ROOT_PASSWORD'),
        database=database
    )

    # Get a cursor for executing SQL statements
    cursor = db.cursor()

    # Execute the select statement to get image_gen_conf for the specified channel
    sql = "SELECT image_gen_conf FROM config WHERE user_id = %s"
    values = (channel_id,)
    cursor.execute(sql, values)

    # Fetch the result and return the image_gen_conf value as a boolean
    result = cursor.fetchone()
    if result:
        return bool(result[0])
    else:
        return False


@bot.command(name="image")
async def cmd_image(ctx, bool_str=None):
    try:
        bool_val = bool(bool_str.lower() == 'true')
        update_image_gen_conf(ctx.channel.id, bool_val)
        await ctx.reply(f'```# image_gen_conf set to {bool_val}```')
    except:
        await ctx.reply('To Change the Image Generation to on please use following.'
                        '```!image <:boolean>```'
                        '\n'
                        'Replace "`<:boolean>`" with "`True`" for Image Generation and "`False`" for no Generation.')


@bot.event
async def on_message(message):
    if message.content.startswith('```#'):
        check_command_responses = ["image_gen_conf"]
        for item in check_command_responses:
            if item in message.content:
                return
    elif message.content.startswith('!'):
        ctx = await bot.get_context(message)
        if ctx.valid:
            await bot.invoke(ctx)
        else:
            command_parts = message.content[1:].split(' ')
            command = command_parts[0]
            arguments = command_parts[1:]

            # Dynamically call the command function if it exists
            command_function = getattr(bot, f'cmd_{command}', None)
            if callable(command_function):
                await command_function(ctx, *arguments)
            else:
                await message.reply(f"Command '{command}' not found.", mention_author=False)
    else:
        if message.author == bot.user:
            if get_image_gen_conf(message.channel.id):
                await message.reply(openai_image_gen(message.content), mention_author=False)
            else:
                return
        elif isinstance(message.channel, discord.DMChannel):
            if message.attachments:
                for attachment in message.attachments:
                    if attachment.filename.endswith('.txt'):
                        # Download the attachment
                        await attachment.save(attachment.filename)
                        # Open the file and get the contents
                        with open(attachment.filename) as file:
                            contents = file.read()
                            message_content = contents
                        # Delete the file
                        os.remove(attachment.filename)
            else:
                message_content = message.content
            logging.info(f'{message.author}:{message_content}')
            dm_channel = await message.author.create_dm()
            async with dm_channel.typing():
                channel_id = str(message.channel.id)
                timestamp_received = int(time.time())
                messages = get_context_from_db(channel_id, time.time())
                if messages is None:
                    messages = {"role": "system", "content": system_instructions}, {"role": "user",
                                                                                    "content": message_content}
                else:
                    messages.append({"role": "user", "content": message_content})
                response = openai_proxy(messages)

                message_parts = split_response(response)

                i = 0
                for part in message_parts:
                    if i == 1:
                        await asyncio.sleep(1)
                        await message.channel.send(part)
                    else:
                        await message.reply(part, mention_author=False)
                    i = 1

                timestamp_sent = int(time.time())
                save_to_database(channel_id, response, "assistant", timestamp_sent)
                save_to_database(channel_id, message_content, "user", timestamp_received)
            return


bot.run(os.getenv('DISCORD_API_KEY'))
