"""
MSDS 697 - PA-1
Simple Test Script for Students
"""

from pymongo import MongoClient
from typing import List, Dict, Any, Optional
from mongo_queries import *


# CONFIGURATION
# TODO: Update these values to match your local MongoDB setup
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "msds697"
COLLECTION_NAME = "open_library"


# TEST FUNCTIONS
print("Testing Query 1...")
result1 = count_paperback_books(MONGO_URI, DB_NAME, COLLECTION_NAME)
print(f"Result: {result1}\n")

print("Testing Query 2...")
result2 = find_english_language_books(MONGO_URI, DB_NAME, COLLECTION_NAME)
print(f"Found {len(result2)} books")
print(f"First result: {result2[0] if result2 else 'None'}\n")

print("Testing Query 3...")
result3 = find_books_over_500_pages(MONGO_URI, DB_NAME, COLLECTION_NAME)
print(f"Found {len(result3)} books")
print(f"First result: {result3[0] if result3 else 'None'}\n")

print("Testing Query 4...")
result4 = count_books_with_isbn13_published_1997(MONGO_URI, DB_NAME, COLLECTION_NAME)
print(f"Result: {result4}\n")

print("Testing Query 5...")
result5 = find_top_10_longest_stationery_office_books(MONGO_URI, DB_NAME, COLLECTION_NAME)
print(f"Found {len(result5)} books")
for i, book in enumerate(result5, 1):
    print(f"  {i}. {book.get('title', 'N/A')} - {book.get('number_of_pages', 'N/A')} pages")
print()

print("Testing Query 6...")
result6 = find_paperback_england_1999_multiple_subjects(MONGO_URI, DB_NAME, COLLECTION_NAME)
print(f"Found {len(result6)} books")
for i, book in enumerate(result6, 1):
    print(f"  {i}. {book.get('title', 'N/A')} ({len(book.get('subjects', []))} subjects)")
print()

print("All tests complete!")

