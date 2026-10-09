"""
Syrus LLM Agent — Google Gemini with typed tools for read-only and order-draft operations.

CRITICAL SAFETY CONSTRAINT:
- Read tools (get_quote, get_portfolio, etc.) execute immediately.
- Write tools (create_order_draft, create_standing_instruction) only produce a draft.
- The LLM cannot place orders. Only the Executor can, and only after a trader-approved token.
"""

import json
from typing import AsyncIterator, Optional
import httpx
import google.generativeai as genai
from google.generativeai.types import content_types

from config import settings

# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are StockItUp, an AI trading copilot for the 021 trading platform.
You help traders manage their portfolio and place orders by understanding plain English requests.

CORE PRINCIPLES:
1. You NEVER place orders. You only create drafts. The trader always has the final say.
2. Before creating any order draft, always fetch the latest quote to show the trader the current price.
3. When the trader's request is ambiguous, ask a clarifying question rather than guessing.
4. Be concise and precise — traders value speed. Give data, not fluff.
5. Always confirm the symbol exists in the instrument master before creating a draft.
6. Format numbers as Indian currency where relevant (₹ with lakh notation for large numbers).

RESPONSE FORMAT:
- For data queries (portfolio, prices, positions): respond naturally with the data, formatted cleanly.
- For order requests: tool call → fetch quote → tool call → create_order_draft → brief acknowledgment.
- Always end order draft responses with: "Review the confirmation card above to approve or reject."
- For standing instructions: confirm the exact rule before creating it.

You have access to live NSE market data via yfinance. Prices are real and updated every 15 seconds."""


class TradingAgent:
    def __init__(self):
        genai.configure(api_key=settings.gemini_api_key)

        # Define tools as Gemini function declarations
        self.tools = [
            genai.protos.Tool(
                function_declarations=[
                    genai.protos.FunctionDeclaration(
                        name="get_quote",
                        description="Get the current live price quote for a stock symbol. Use this whenever the trader asks about a stock price, bid/ask, volume, or day range. Symbol format: RELIANCE.NS, INFY.NS, TCS.NS, NIFTY50, etc.",
                        parameters=content_types.to_function_library({
                            "type": "object",
                            "properties": {
                                "symbol": {"type": "string", "description": "NSE stock symbol e.g. RELIANCE.NS, INFY.NS, NIFTY50"}
                            },
                            "required": ["symbol"]
                        })["properties"][0]
                    ),
                    genai.protos.FunctionDeclaration(
                        name="get_portfolio",
                        description="Get the trader's account summary: available funds, total portfolio value, funds used. Use when the trader asks about account balance, funds, or overall portfolio value.",
                        parameters=content_types.to_function_library({
                            "type": "object",
                            "properties": {}
                        })["properties"][0]
                    ),
                    genai.protos.FunctionDeclaration(
                        name="get_positions",
                        description="Get all current open positions with live P&L. Use when the trader asks about positions, holdings, unrealized P&L, or exposure.",
                        parameters=content_types.to_function_library({
                            "type": "object",
                            "properties": {}
                        })["properties"][0]
                    ),
                    genai.protos.FunctionDeclaration(
                        name="get_order_history",
                        description="Get recent order history. Use when the trader asks what orders have been placed, filled, cancelled, etc.",
                        parameters=content_types.to_function_library({
                            "type": "object",
                            "properties": {
                                "status": {"type": "string", "description": "Filter by order status. Options: ALL, FILLED, PARTIAL, REJECTED, CANCELLED"}
                            }
                        })["properties"][0]
                    ),
                    genai.protos.FunctionDeclaration(
                        name="search_instrument",
                        description="Search the instrument master to find valid symbols and their details. Use to verify a symbol before including it in an order draft.",
                        parameters=content_types.to_function_library({
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Search term e.g. 'Reliance', 'INFY', 'HDFC Bank'"}
                            },
                            "required": ["query"]
                        })["properties"][0]
                    ),
                    genai.protos.FunctionDeclaration(
                        name="create_order_draft",
                        description="Create a draft order for the trader to review and approve. NEVER use this without first calling get_quote to get the latest price. This does NOT place an order — it only creates a draft that the trader must approve. The system will validate symbol, check risk limits, and display a confirmation card.",
                        parameters=content_types.to_function_library({
                            "type": "object",
                            "properties": {
                                "symbol": {"type": "string", "description": "Valid NSE symbol"},
                                "side": {"type": "string", "description": "BUY or SELL"},
                                "order_type": {"type": "string", "description": "MARKET, LIMIT, SL, or SL-M"},
                                "quantity": {"type": "integer", "description": "Number of shares"},
                                "price": {"type": "number", "description": "Required for LIMIT/SL orders"},
                                "trigger_price": {"type": "number", "description": "Required for SL/SL-M orders"},
                                "rationale": {"type": "string", "description": "Brief explanation of this order"}
                            },
                            "required": ["symbol", "side", "order_type", "quantity"]
                        })["properties"][0]
                    ),
                    genai.protos.FunctionDeclaration(
                        name="create_standing_instruction",
                        description="Create a standing instruction (rule) that will automatically trigger an order when a condition is met. Example: 'If INFY drops below 1750, sell 50 shares'. The rule is stored and checked against live prices. It fires exactly once. Always show the trader the exact condition and action before creating — they must approve it.",
                        parameters=content_types.to_function_library({
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Short name for this rule"},
                                "symbol": {"type": "string"},
                                "condition_type": {"type": "string", "description": "PRICE_ABOVE, PRICE_BELOW, or PERCENT_CHANGE"},
                                "condition_value": {"type": "number", "description": "Price level or percent threshold"},
                                "action_side": {"type": "string", "description": "BUY or SELL"},
                                "action_quantity": {"type": "integer", "description": "Number of shares"},
                                "action_order_type": {"type": "string", "description": "MARKET or LIMIT"},
                                "expires_in_hours": {"type": "number", "description": "Auto-expire after N hours"}
                            },
                            "required": ["name", "symbol", "condition_type", "condition_value", "action_side", "action_quantity"]
                        })["properties"][0]
                    )
                ]
            )
        ]

        self.model = genai.GenerativeModel(
            model_name='gemini-1.5-pro',
            tools=self.tools,
            system_instruction=SYSTEM_PROMPT
        )
        self.broker_url = settings.mock_api_url

    async def _call_tool(self, tool_name: str, tool_input: dict) -> str:
        """Execute a tool call and return the result as a JSON string."""
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
                    # These don't call the broker — they return a structured draft
                    # that the router will intercept and process
                    return json.dumps({"draft": True, "data": tool_input, "tool": tool_name})

                else:
                    return json.dumps({"error": f"Unknown tool: {tool_name}"})

            except httpx.RequestError as e:
                return json.dumps({"error": f"Broker API unreachable: {str(e)}"})

    async def stream(
        self,
        messages: list[dict],
        on_draft: Optional[callable] = None,
    ) -> AsyncIterator[str]:
        """
        Stream a response from Gemini, handling function calls in an agentic loop.
        Yields SSE-formatted server-sent event strings.

        on_draft: async callback called when a draft tool result is produced.
                  Receives (tool_name, tool_input) — used by the router to save the draft to DB.
        """
        # Convert message history to Gemini format
        chat_history = []
        for msg in messages[:-1]:  # All except the last one
            role = "user" if msg["role"] == "user" else "model"
            content = msg["content"]
            if isinstance(content, str):
                chat_history.append({"role": role, "parts": [content]})
            else:
                # Handle complex content (tool results, etc.)
                chat_history.append({"role": role, "parts": [str(content)]})

        # Start chat session
        chat = self.model.start_chat(history=chat_history)

        # Get the last user message
        user_message = messages[-1]["content"] if messages else ""

        max_iterations = 10
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            try:
                # Send message and get response
                response = chat.send_message(user_message)

                # Process response parts
                has_function_calls = False

                for part in response.parts:
                    # Handle text response
                    if part.text:
                        text = part.text
                        # Stream text in chunks for better UX
                        chunk_size = 50
                        for i in range(0, len(text), chunk_size):
                            chunk = text[i:i+chunk_size]
                            yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"

                    # Handle function call
                    elif part.function_call:
                        has_function_calls = True
                        func_call = part.function_call
                        tool_name = func_call.name
                        tool_args = dict(func_call.args)

                        yield f"data: {json.dumps({'type': 'tool_call', 'tool': tool_name, 'input': tool_args})}\n\n"

                        # Execute the tool
                        result_str = await self._call_tool(tool_name, tool_args)
                        result_data = json.loads(result_str)

                        # If it's a draft tool, fire the callback
                        if result_data.get("draft") and on_draft:
                            await on_draft(tool_name, tool_args)
                            yield f"data: {json.dumps({'type': 'draft', 'tool': tool_name, 'data': tool_args})}\n\n"

                        # Send function response back to model
                        function_response = genai.protos.Part(
                            function_response=genai.protos.FunctionResponse(
                                name=tool_name,
                                response={"result": result_data}
                            )
                        )

                        # Continue the conversation with function result
                        user_message = None
                        response = chat.send_message(function_response)

                        # Process the response after function call
                        for part in response.parts:
                            if part.text:
                                text = part.text
                                chunk_size = 50
                                for i in range(0, len(text), chunk_size):
                                    chunk = text[i:i+chunk_size]
                                    yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"

                # Check if conversation is complete (no more function calls)
                if not has_function_calls:
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    break

            except Exception as e:
                error_msg = f"Error: {str(e)}"
                yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break

        # If we hit max iterations, send done
        if iteration >= max_iterations:
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
