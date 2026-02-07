////////////////////////////////////////////////////////
//     To run this script mongo < day1_examples.js    //
////////////////////////////////////////////////////////

// Array – [Element1, Element2,…]
diane = {"favorite": ["Children"]}

diane = {"favorite": ["Children", 7, ["Database", "Machine Learning"]]}

// Embeded Documents
diane = {"name" : "Diane MK Woodbridge",
         "address" : {"street" : "101 Howard St", "city" : "San Francisco",
         "state" : "CA"}}

//ObjectId
ObjectId()

//Basic Math
x = 200
x / 23

//JavaScript
Math.sin(Math.PI)

msds_string = "USF MSDS"
msds_string = msds_string.replace("MSDS", "Master in Data Science")

// Example 1 
// Create msds697 database and create a collection called "friends".
// Insert diane and yannet to "friends".
// Create and insert "Diane" document into the collection.

diane = {"name" : "Diane MK Woodbridge",
         "address" : {"street" : "101 Howard St", "city" : "San Francisco",
         "state" : "CA"}}
yannet = {"name":"Yannet Interian", 
          "address" : {"street" : "101 Howard", "city" : "San Francisco", 
          "state" : "CA"}}
shan = {"name":"Shan Wang"}          
     

// Create/Insert


//Bulk Insert 


// Example 2
//Import raw data - do it on the terminal (not on Mongo shell

//mongoimport --db msds697 --collection business --file ../Data/business.json


// Example 3
// Find all documents where address’s city is San Francisco.

// Find one document where address’s city is San Francisco.


// Example 4
//Find all businesses in "Manhattan" in "business" under the “msds697” database.

//Only business names?


// Example 5
// Set "title" as "Associate Professor", to all the documents 
// where "name" is set as "Diane MK Woodbridge".



//Unset "title", to all the documents,  
// where "name" is set as "Diane MK Woodbridge”.

                   
// Set "title" as "Administrative Director", to all the documents 
// where "name" is set as "Aija Tapaninen".
// If there is no corresponding document, create one.





// Example 6
// Increase "kidsCount" by 1 for all documents, where "name" is "Shan Wang".


// Rename "address" field to "officeAddress" for all the documents.



// Example 7
// In the "business" collection, for "White Castle" on "Pennsylvania Avenue" , 
// insert a new grades with "date" : today, "grade" : "A", and "score" : 9.
db.business.find({"name":"White Castle", "address.street":"Pennsylvania Avenue"})


// Remove the last grades for for "White Castle" on "Pennsylvania Avenue" 



// Remove all reviews with Cs for restaurant_id, 40364467 .



// Example 8
//Change all scores of "40356483" from 10 to 11.
//$


//$[] 
db.business.drop()
//mongoimport --db msds697 --collection business --file business.json

	   
//$[<identifier>]
db.business.drop()
//mongoimport --db msds697 --collection business --file business.json



// Example 9
// In "friends" collection,
// Delete one item which officeAddress' city is “San Francisco”
// Delete all items which officeAddress' city is “San Francisco”
// What is the best way to drop all? 
//// .deleteMany({}) vs .drop()

//Remove One


//Remove Many


//Drop the entire collection.



//Extra -
// For documents in business where zipcode is 10462, and street is "Castle Hill Avenue",
// Update its grade to "A+" if score is greater than 10.
db.business.find({"address.zipcode" : "10462", "address.street" : "Castle Hill Avenue"})

