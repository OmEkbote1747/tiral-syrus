"""
Syrus LLM Agent — Google Gemini with function calling for trading operations.
Simplified and robust implementation.
"""

import json
from typing import AsyncIterator, Optional
import httpx
import google.generativeai as genai

from config import settings

SYSTEM_PROMPT = """You are StockItUp, an AI trading copilot for the 021 trading platform.
You help traders manage their portfolio and place orders by understanding plain English requests.

CORE PRINCIPLES:
1. You NEVER place orders. You only create drafts. The trader always has the final say.
2. Before creating any order draft, always fetch the latest quote to show the trader the current price.
3. When the trader's request is ambiguous, ask a clarifying question rather than guessing.
4. Be concise and precise — traders value speed. Give data, not fluff.
5. Always confirm the symbol exists in the instrument master before creating a draft.
6. Format numbers as Indian currency where relevant (₹ with lakh notation for large numbers).

You have access to live NSE market data. Prices are real and updated every 15 seconds."""


class TradingAgent:
    def __init__(self):
        genai.configure(api_key=settings.gemini_api_key)

        # Define tools using Gemini's expected format
        tools = [
            genai.protos.Tool(
                function_declarations=[
                    genai.protos.FunctionDeclaration(
                        name="get_quote",
                        description="Get live stock price quote. Symbol format: RELIANCE.NS, INFY.NS, TCS.NS",
                        parameters=genai.protos.Schema(
                            type=genai.protos.Type.OBJECT,
                            properties={
                                "symbol": genai.protos.Schema(type=genai.protos.Type.STRING, description="NSE stock symbol")
                            },
                            required=["symbol"]
                        )
                    ),
                    genai.protos.FunctionDeclaration(
                        name="get_portfolio",
                        description="Get account summary: funds, portfolio value",
                        parameters=genai.protos.Schema(type=genai.protos.Type.OBJECT, properties={})
                    ),
                    genai.protos.FunctionDeclaration(
                        name="get_positions",
                        description="Get open positions with P&L",
                        parameters=genai.protos.Schema(type=genai.protos.Type.OBJECT, properties={})
                    ),
                    genai.protos.FunctionDeclaration(
                        name="get_order_history",
                        description="Get order history",
                        parameters=genai.protos.Schema(
                            type=genai.protos.Type.OBJECT,
                            properties={
                                "status": genai.protos.Schema(type=genai.protos.Type.STRING, description="ALL, FILLED, PARTIAL, REJECTED, CANCELLED")
                            }
                        )
                    ),
                    genai.protos.FunctionDeclaration(
                        name="search_instrument",
                        description="Search for valid stock symbols",
                        parameters=genai.protos.Schema(
                            type=genai.protos.Type.OBJECT,
                            properties={
                                "query": genai.protos.Schema(type=genai.protos.Type.STRING, description="Search term")
                            },
                            required=["query"]
                        )
                    ),
                    genai.protos.FunctionDeclaration(
                        name="create_order_draft",
                        description="Create order draft for trader approval. NEVER place orders directly.",
                        parameters=genai.protos.Schema(
                            type=genai.protos.Type.OBJECT,
                            properties={
                                "symbol": genai.protos.Schema(type=genai.protos.Type.STRING),
                                "side": genai.protos.Schema(type=genai.protos.Type.STRING, description="BUY or SELL"),
                                "order_type": genai.protos.Schema(type=genai.protos.Type.STRING, description="MARKET, LIMIT, SL, SL-M"),
                                "quantity": genai.protos.Schema(type=genai.protos.Type.INTEGER),
                                "price": genai.protos.Schema(type=genai.protos.Type.NUMBER, description="For LIMIT orders"),
                                "trigger_price": genai.protos.Schema(type=genai.protos.Type.NUMBER, description="For SL orders"),
                                "rationale": genai.protos.Schema(type=genai.protos.Type.STRING)
                            },
                            required=["symbol", "side", "order_type", "quantity"]
                        )
                    ),
                    genai.protos.FunctionDeclaration(
                        name="create_standing_instruction",
                        description="Create standing instruction rule",
                        parameters=genai.protos.Schema(
                            type=genai.protos.Type.OBJECT,
                            properties={
                                "name": genai.protos.Schema(type=genai.protos.Type.STRING),
                                "symbol": genai.protos.Schema(type=genai.protos.Type.STRING),
                                "condition_type": genai.protos.Schema(type=genai.protos.Type.STRING, description="PRICE_ABOVE, PRICE_BELOW, PERCENT_CHANGE"),
                                "condition_value": genai.protos.Schema(type=genai.protos.Type.NUMBER),
                                "action_side": genai.protos.Schema(type=genai.protos.Type.STRING, description="BUY or SELL"),
                                "action_quantity": genai.protos.Schema(type=genai.protos.Type.INTEGER),
                                "action_order_type": genai.protos.Schema(type=genai.protos.Type.STRING, description="MARKET or LIMIT"),
                                "expires_in_hours": genai.protos.Schema(type=genai.protos.Type.NUMBER)
                            },
                            required=["name", "symbol", "condition_type", "condition_value", "action_side", "action_quantity"]
                        )
                    )
                ]
            )
        ]

        self.model = genai.GenerativeModel(
            model_name='gemini-1.5-pro',
            tools=tools,
            system_instruction=SYSTEM_PROMPT
        )
        self.broker_url = settings.mock_api_url

    async def _call_tool(self, tool_name: str, tool_input: dict) -> str:
        """Execute a tool call and return result as JSON string."""
        async with httpx.AsyncClient(timeout=10.0) as http:
            try:
                if tool_name == "get_quote":
                    r = await http.get(f"{self.broker_url}/quote/{tool_input['symbol']}")
                    return json.dumps(r.json())

                elif tool_name == "get_portfolio":
                    r = await http.get(f"{self.broker_url}/account")
                    return json.dumps(r.json())

                elif tool_name == "get_positions":
                    r = await http.get(f"{self.broker_url}/positions")
                    return json.dumps(r.json())

                elif tool_name == "get_order_history":
                    status = tool_input.get("status", "ALL")
                    r = await http.get(f"{self.broker_url}/orders", params={"status": status})
                    return json.dumps(r.json())

                elif tool_name == "search_instrument":
                    r = await http.get(f"{self.broker_url}/instruments", params={"search": tool_input["query"]})
                    return json.dumps(r.json())

                elif tool_name in ("create_order_draft", "create_standing_instruction"):
                    return json.dumps({"draft": True, "data": tool_input, "tool": tool_name})

                else:
                    return json.dumps({"error": f"Unknown tool: {tool_name}"})

            except Exception as e:
                return json.dumps({"error": f"API error: {str(e)}"})

    async def stream(
        self,
        messages: list[dict],
        on_draft: Optional[callable] = None,
    ) -> AsyncIterator[str]:
        """Stream response from Gemini with function calling."""

        # Convert to Gemini format
        chat_history = []
        for msg in messages[:-1]:
            role = "user" if msg["role"] == "user" else "model"
            content = msg["content"]
            if isinstance(content, str):
                chat_history.append({"role": role, "parts": [content]})

        chat = self.model.start_chat(history=chat_history)
        user_message = messages[-1]["content"] if messages else ""

        max_iterations = 10
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            try:
                response = chat.send_message(user_message)
                has_function_calls = False

                for part in response.parts:
                    if part.text:
                        # Stream text
                        text = part.text
                        for i in range(0, len(text), 50):
                            chunk = text[i:i+50]
                            yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"

                    elif hasattr(part, 'function_call') and part.function_call:
                        has_function_calls = True
                        func_call = part.function_call
                        tool_name = func_call.name
                        tool_args = dict(func_call.args)

                        yield f"data: {json.dumps({'type': 'tool_call', 'tool': tool_name, 'input': tool_args})}\n\n"

                        # Execute tool
                        result_str = await self._call_tool(tool_name, tool_args)
                        result_data = json.loads(result_str)

                        # Handle drafts
                        if result_data.get("draft") and on_draft:
                            await on_draft(tool_name, tool_args)
                            yield f"data: {json.dumps({'type': 'draft', 'tool': tool_name, 'data': tool_args})}\n\n"

                        # Send result back to model
                        user_message = None
                        response = chat.send_message([
                            genai.protos.Part(
                                function_response=genai.protos.FunctionResponse(
                                    name=tool_name,
                                    response={"result": result_data}
                                )
                            )
                        ])

                        # Stream response after function call
                        for part in response.parts:
                            if part.text:
                                text = part.text
                                for i in range(0, len(text), 50):
                                    chunk = text[i:i+50]
                                    yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"

                if not has_function_calls:
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    break

            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'content': f'Error: {str(e)}'})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break

        if iteration >= max_iterations:
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
