import os
from langchain_openai import ChatOpenAI, AzureChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.chat_models import ChatOllama

def get_llm_response(messages):
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()

    if provider == "gemini":
        api_key = os.getenv("GOOGLE_API_KEY")
        credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        if not api_key and not credentials_path:
            raise ValueError("Either GOOGLE_API_KEY or GOOGLE_APPLICATION_CREDENTIALS must be set.")

        if api_key:
            llm = ChatGoogleGenerativeAI(
                model=model_name,
                google_api_key=api_key,
                temperature=0.7
            )
        else:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
            llm = ChatGoogleGenerativeAI(model=model_name, temperature=0.7)

        try:
            response = llm.invoke(messages)
            return response.content
        except Exception as e:
            raise RuntimeError(f"Gemini call failed: {e}")

    elif provider == "azure":
        api_key = os.getenv("AZURE_OPENAI_KEY")
        api_base = os.getenv("AZURE_OPENAI_BASE")
        api_version = os.getenv("AZURE_API_VERSION")
        deployment_name = os.getenv("AZURE_DEPLOYMENT_NAME", "gpt-4o")

        if not all([api_key, api_base, api_version]):
            raise ValueError("Missing one of AZURE_OPENAI_KEY, AZURE_OPENAI_BASE, or AZURE_API_VERSION.")

        llm = AzureChatOpenAI(
            azure_deployment=deployment_name,
            openai_api_version=api_version,
            azure_endpoint=api_base,
            api_key=api_key,
            temperature=0.7
        )
        try:
            response = llm.invoke(messages)
            return response.content
        except Exception as e:
            raise RuntimeError(f"Azure OpenAI call failed: {e}")

    elif provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
        model_name = os.getenv("OPENAI_MODEL", "gpt-4o")

        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set.")

        llm = ChatOpenAI(model=model_name, api_key=api_key, base_url=api_base, temperature=0.7)
        try:
            response = llm.invoke(messages)
            return response.content
        except Exception as e:
            raise RuntimeError(f"OpenAI call failed: {e}")

    elif provider == "ollama":
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        model = os.getenv("OLLAMA_MODEL", "llama3")

        llm = ChatOllama(model=model, base_url=ollama_url, temperature=0.7)
        try:
            response = llm.invoke(messages)
            return response.content
        except Exception as e:
            raise RuntimeError(f"Ollama call failed: {e}")

    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")
