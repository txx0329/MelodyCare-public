import os
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma
from dotenv import load_dotenv

load_dotenv()

KNOWLEDGE_BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "knowledge_base")
VECTOR_DB_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "vector_store")


def build_vector_store():
    api_key = os.getenv("GOOGLE_API_KEY")
    print("Loading documents...")
    loader = DirectoryLoader(
        KNOWLEDGE_BASE_DIR,
        glob="**/*.txt",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
    )
    documents = loader.load()
    print(f"Loaded {len(documents)} documents.")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=80,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(documents)
    print(f"Split into {len(chunks)} chunks.")

    print("Building vector store...")
    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=api_key,
    )
    vector_store = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=VECTOR_DB_DIR,
    )
    print("Done! Vector store ready.")
    return vector_store


if __name__ == "__main__":
    build_vector_store()