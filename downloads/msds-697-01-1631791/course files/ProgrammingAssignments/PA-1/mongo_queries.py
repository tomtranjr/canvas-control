"""
MSDS 697 - PA-1
MongoDB Queries Template

Instructions:
- Complete each function below with the appropriate MongoDB query
- Do not modify the function signatures
- Test your queries using run_mongo.py
- All queries should work with the provided editions_final.json dataset
"""
from pymongo import MongoClient

def get_collection(MONGO_URI: str, DB_NAME: str, COLLECTION_NAME: str):
    """
    Establishes connection to MongoDB and returns the collection.
    DO NOT MODIFY THIS FUNCTION.
    """
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    return db[COLLECTION_NAME]


# QUERY 1: Basic Filtering [10 points]
def count_paperback_books(MONGO_URI: str, DB_NAME: str, COLLECTION_NAME: str):
    """
    Count the total number of book editions where the physical_format 
    is exactly "Paperback".
    
    Returns:
        int: Count of paperback books
    """
    collection = get_collection(MONGO_URI, DB_NAME, COLLECTION_NAME)
    
    # TODO: Write your query here
    # Hint: Use count_documents() with a filter for physical_format

    pass  # Remove this line and add your code

# QUERY 2: Array Membership & Projection [10 points]
def find_english_language_books(MONGO_URI: str, DB_NAME: str, COLLECTION_NAME: str):
    """
    Find all editions where the languages array contains an object with 
    key "/languages/eng". Return only the title, publish_date, and languages 
    fields (exclude _id).
    
    Returns:
        List[Dict]: List of books with selected fields
    """
    collection = get_collection(MONGO_URI, DB_NAME, COLLECTION_NAME)
    
    # TODO: Write your query here

    pass  # Remove this line and add your code


# QUERY 3: Numerical Comparisons [15 points]
def find_books_over_500_pages(MONGO_URI: str, DB_NAME: str, COLLECTION_NAME: str):
    """
    Find all book editions where number_of_pages is greater than 500.
    Return the title, isbn_13 (or isbn_10), and number_of_pages fields 
    (exclude _id).
    
    Returns:
        List[Dict]: List of books with selected fields
    """
    collection = get_collection(MONGO_URI, DB_NAME, COLLECTION_NAME)
    
    # TODO: Write your query here

    pass  # Remove this line and add your code


# QUERY 4: Array Length/Existence & Filtering [15 points]
def count_books_with_isbn13_published_1997(MONGO_URI: str, DB_NAME: str, COLLECTION_NAME: str):
    """
    Count the total number of editions that have at least one ISBN-13 listed
    (i.e., the isbn_13 field exists and is not empty) and were published 
    in the year "1997".
    
    Note: Since publish_date is a string like "July 1997", you will need 
    to use a regular expression.
    
    Returns:
        int: Count of books with ISBN-13 published in 1997
    """
    collection = get_collection(MONGO_URI, DB_NAME, COLLECTION_NAME)
    
    # TODO: Write your query here

    pass  # Remove this line and add your code


# QUERY 5: Sorting and Limiting [20 points]
def find_top_10_longest_stationery_office_books(MONGO_URI: str, DB_NAME: str, COLLECTION_NAME: str):
    """
    Find the top 10 longest books (based on number_of_pages) that were 
    published by "Stationery Office Books". Return only the title and 
    the number_of_pages, sorted from most pages to least.
    
    Returns:
        List[Dict]: List of top 10 longest books with selected fields
    """
    collection = get_collection(MONGO_URI, DB_NAME, COLLECTION_NAME)
    
    # TODO: Write your query here

    pass  # Remove this line and add your code


# QUERY 6: Complex Filtering and Array Logic [30 points]
def find_paperback_england_1999_multiple_subjects(MONGO_URI: str, DB_NAME: str, COLLECTION_NAME: str):
    """
    Find the first five paperback book editions published in England 
    (country code "enk") during the year 1999 that also contain more than 
    one subject listed in their subjects array. Return only the title, 
    the subjects list, and the publish_date for these specific records.
    
    Returns:
        List[Dict]: List of up to 5 books with selected fields
    """
    collection = get_collection(MONGO_URI, DB_NAME, COLLECTION_NAME)
    
    # TODO: Write your query here

    pass  # Remove this line and add your code