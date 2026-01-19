from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from ddgs import DDGS
from typing import TypedDict, Annotated
from operator import add
from langchain_core.tools import tool
from langchain_core.messages import ToolMessage, AIMessage, HumanMessage
from langgraph.graph import StateGraph, END


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


llm_with_tools = llm.bind_tools([search_web])

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

            tool_message = ToolMessage(content=result,tool_call_id=tool_call["id"])
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
        "messages": [HumanMessage(content="What Python remote jobs are available right now?")]
    }
    
    result = app.invoke(initial_state)

    print("Final messages:")
    for msg in result["messages"]:
        print(f"\n{type(msg).__name__}:")
        print(msg.content)