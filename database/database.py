from neo4j import GraphDatabase
import os

URI = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "your_password")

driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))

def verify_connection():
    driver.verify_connectivity()

def close_driver():
    driver.close()
