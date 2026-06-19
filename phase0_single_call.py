import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# --- DeepSeek (commented out) ---
# client = OpenAI(
#     base_url="https://api.deepseek.com",
#     api_key=os.environ.get("DEEPSEEK_API_KEY")
# )
# MODEL = "deepseek-chat"

# --- Google AI Studio (Gemini), via its OpenAI-compatible endpoint ---
client = OpenAI(
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_key=os.environ.get("GOOGLE_API_KEY")
)
MODEL = "gemini-2.0-flash"

# Step 2: Define the tool using the standard OpenAI/DeepSeek function format.
tools = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a text file from disk.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file to read.",
                    }
                },
                "required": ["path"],
            },
        }
    }
]

# Step 3: Ask something that requires information the model doesn't have.
response = client.chat.completions.create(
    model=MODEL,
    max_tokens=1024,
    tools=tools,
    messages=[
        {
            "role": "user",
            "content": "What does sample.txt say? Use the read_file tool to find out.",
        }
    ],
)

# The model returns the message structure within the first choice object
message = response.choices[0].message

print("=" * 60)
print("RAW RESPONSE FROM MODEL")
print("=" * 60)

# Check if the model provided a text explanation before using the tool
if message.content:
    print("\n--- Content type: text ---")
    print(message.content)

# Check if the model requested any tool executions
if message.tool_calls:
    for tool_call in message.tool_calls:
        print(f"\n--- Content type: tool_use ---")
        print(f"Tool requested: {tool_call.function.name}")
        print(f"Tool input:     {tool_call.function.arguments}")
        print(f"Tool use id:    {tool_call.id}")

print("\n" + "=" * 60)
print("finish_reason:", response.choices[0].finish_reason)
print("=" * 60)

# Step 4: Act on the stop reason
if response.choices[0].finish_reason == "tool_calls":
    print("\n👉 The model is WAITING on you.")
    print("   This is the exact seam where harnesses and loops attach:")
    print("   something has to execute read_file() and send the result back.")
    print("   That's Phase 1.")