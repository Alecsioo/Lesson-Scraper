from neo4j import GraphDatabase
from dotenv import load_dotenv
import os
import certifi

load_dotenv()
os.environ["SSL_CERT_FILE"] = certifi.where()

URI = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
USERNAME = os.getenv("NEO4J_USERNAME")
PASSWORD = os.getenv("NEO4J_PASSWORD")

print(f"Connecting to {URI}")
driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))


def verify_connection():
    driver.verify_connectivity()


def close_driver():
    driver.close()
