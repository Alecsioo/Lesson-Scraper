# Exposes methods to query a GraphQL backend and structure the returned data
import os
import requests

from classes import Chapter


# Given a GraphQL JSON, extracts a list of chapters for each level in the course (A2, A1, ...)
def extract_chapters_by_level(course_pack: str, learning_language: str) -> list[list[Chapter]]:
    chapters_by_level: list[list[Chapter]] = []

    graphql_url = os.getenv("GRAPHQL_URL")

    payload = {
        "operationName": "getChapters",
        "variables": {
            "id": course_pack,
            "learningLanguage": learning_language,
            "interfaceLanguage": "en",
        },
        "query": """query getChapters($id: String!, $learningLanguage: String!, $interfaceLanguage: String!) {
        course(id: $id, context: {learningLanguage: $learningLanguage}) {
          levels {
            edges {
              node {
                chapters {
                  edges {
                    node {
                      title {
                        id
                        interface(language: $interfaceLanguage) { value __typename }
                        __typename
                      }
                      __typename
                    }
                    __typename
                  }
                  __typename
                }
                __typename
              }
              __typename
            }
            __typename
          }
          __typename
        }
      }"""
    }

    headers = {
        "content-type": "application/json",
        "accept": "application/json",
    }

    r = requests.post(graphql_url, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()

    levels = (data.get("data", {})
              .get("course", {})
              .get("levels", {})
              .get("edges", []))

    for lvl_edge in levels:
        lvl_node = (lvl_edge or {}).get("node", {}) or {}
        ch_edges = (lvl_node.get("chapters", {}) or {}).get("edges", [])

        chapter_titles = []
        for ch_edge in ch_edges:
            ch_node = (ch_edge or {}).get("node", {}) or {}
            title_obj = ch_node.get("title", {}) or {}
            iface = title_obj.get("interface", {}) or {}
            chapter = Chapter(name=iface.get("value") or title_obj.get("id") or "<no-title>")
            chapter_titles.append(chapter)

        chapters_by_level.append(chapter_titles)

    return chapters_by_level
