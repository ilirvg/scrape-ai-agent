import asyncio
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from ddgs import DDGS
from typing import TypedDict, Annotated
from operator import add
from langchain_core.tools import tool
from langchain_core.messages import ToolMessage, AIMessage, HumanMessage
from langgraph.graph import StateGraph, END
from crawl4ai import AsyncWebCrawler, RateLimiter

class AgentState(TypedDict):
    messages: Annotated[list, add]


load_dotenv()

llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")

# response = llm.invoke("What makes a good Python job posting?")
# print(response.content)

@tool
def search_web(query: str) -> str:
    """Searches the web for information. Use this when you need to find current information, job listings, or any web content.
    
    Args:
        query: The search query to look for on the web
    """
    formatted_results = []
    with DDGS() as ddgs:
        results = ddgs.text(query,  max_results=5)

    for result in results:
        formatted = f"Title: {result['title']}\nURL: {result['href']}\nSummary: {result['body']}\n---"
        formatted_results.append(formatted)

    return "\n".join(formatted_results)

async def _scrape(url: str) -> str:
    try:
        async with AsyncWebCrawler(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            wait_for="css:body",
            js_code="""
            // Wait for dynamic content to load
            await new Promise(resolve => setTimeout(resolve, 2000));
            """
        ) as crawler:
            result = await crawler.arun(url=url)
            if result.status_code and result.status_code != 200:
                return f"Error: Could not access page (HTTP {result.status_code}). The site may have blocked the request"
            
            content = result.markdown or result.cleaned_html
            if not content:
                return "Error: Could not extract content from the page"

            if len(content) > 10000:
                return content[:10000] + "\n\n[Content truncated - page was too long]"

            return content
    except Exception as e:
        return f"Error scraping page: {str(e)}. The site may have anti-scraping measures"

@tool
def scrape_page(url: str) -> str:
    """Scrapes a web page and returns its content as markdown. Use this to read the full content of a job posting page.
    
    Args:
        url: The URL of the page to scrape
    """
    return asyncio.run(_scrape(url))

llm_with_tools = llm.bind_tools([search_web, scrape_page])

def agent_node(state: AgentState) -> AgentState:
    messages = state["messages"]
    if not messages:
        return {"messages": []}
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}

def tool_node(state: AgentState) -> AgentState:
    last_message = state["messages"][-1]

    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return {"messages": []}
    
    tool_messages = []
    for tool_call in last_message.tool_calls:
        if tool_call["name"] == "search_web":
            result = search_web.invoke(tool_call["args"])
            tool_message = ToolMessage(content=result, tool_call_id=tool_call["id"])
            tool_messages.append(tool_message)

        elif tool_call["name"] == "scrape_page":
            result = scrape_page.invoke(tool_call["args"])
            tool_message = ToolMessage(content=result, tool_call_id=tool_call["id"])
            tool_messages.append(tool_message)
    
    return {"messages": tool_messages}

def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return END

graph = StateGraph(AgentState)
graph.add_node("agent", agent_node)
graph.add_node("tools", tool_node)
graph.set_entry_point("agent")
graph.add_conditional_edges("agent", should_continue)
graph.add_edge("tools", "agent")

app = graph.compile()

if __name__ == "__main__":
    

    initial_state = {
        "messages": [HumanMessage(content="Find me Python remote jobs and scrape the first job posting you find")]
    }
    
    result = app.invoke(initial_state)

    print("Final messages:")
    for msg in result["messages"]:
        print(f"\n{type(msg).__name__}:")
        print(msg.content)