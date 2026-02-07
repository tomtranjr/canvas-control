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
use msds697
db.dropDatabase()
db.createCollection('friends')

db.friends.insertOne(diane)
db.friends.find()


//Bulk Insert 
db.friends.insertMany([yannet, shan])
db.friends.find()


// Example 2
//Import raw data - do it on the terminal (not on Mongo shell

//mongoimport --db msds697 --collection business --file ../Data/business.json
use msds697
db.business.findOne()

// Example 3
// Find all documents where address’s city is San Francisco.
db.friends.find({"address.city":"San Francisco"})
// Find one document where address’s city is San Francisco.
db.friends.findOne({"address.city":"San Francisco"})

// Example 4
//Find all businesses in "Manhattan" in "business" under the “msds697” database.
db.business.find({"borough":"Manhattan"})
//Only business names?
db.business.find({"borough":"Manhattan"},{"name":true,"_id":false})


// Example 5
// Set "title" as "Associate Professor", to all the documents 
// where "name" is set as "Diane MK Woodbridge".
db.friends.updateMany({"name":"Diane MK Woodbridge"}, 
                      {$set:{"title":"Associate Professor"}})
db.friends.find({"name":"Diane MK Woodbridge"})

//Unset "title", to all the documents,  
// where "name" is set as "Diane MK Woodbridge”.
db.friends.updateMany({"name":"Diane MK Woodbridge"}, 
                      {$unset:{"title":""}})
db.friends.find({"name":"Diane MK Woodbridge"})
                      
// Set "title" as "Administrative Director", to all the documents 
// where "name" is set as "Aija Tapaninen".
// If there is no corresponding document, create one.
db.friends.updateMany({"name":"Aija Tapaninen"}, 
                 {$set:{"title":"Administrative Director"}}, 
                 {upsert : true})
db.friends.find({"name":"Aija Tapaninen"})



// Example 6
// Increase "kidsCount" by 1 for all documents, where "name" is "Shan Wang".
db.friends.updateMany({"name" : "Shan Wang"}, {$inc:{"kidsCount" : 1}})
db.friends.find({"name" : "Shan Wang"})

// Rename "address" field to "officeAddress" for all the documents.
db.friends.updateMany({},{$rename : {"address":"officeAddress"}})
db.friends.find()


// Example 7
// In the "business" collection, for "White Castle" on "Pennsylvania Avenue" , 
// insert a new grades with "date" : today, "grade" : "A", and "score" : 9.
db.business.find({"name":"White Castle", "address.street":"Pennsylvania Avenue"})
db.business.updateMany({"name":"White Castle" ,"address.street":"Pennsylvania Avenue"}, 
                   {$push : {"grades": {
                                        "date" : new Date() ,
                                        "grade" : "A", 
                                        "score" : NumberInt(9)
                                       }
                             }
                   })
db.business.find({"name":"White Castle", "address.street":"Pennsylvania Avenue"})   

// Remove the last grades for for "White Castle" on "Pennsylvania Avenue" 
db.business.updateMany({"name":"White Castle" ,
                        "address.street":"Pennsylvania Avenue"},
                    {$pop:{"grades":1}})
db.business.find({"name":"White Castle", "address.street":"Pennsylvania Avenue"})   


// Remove all reviews with Cs for restaurant_id, 40364467 .
db.business.find({"restaurant_id" : "40364467"}) // Two Cs
db.business.updateMany({"restaurant_id" : "40364467"},
                   {$pull:{"grades":{"grade":"C"}}})
db.business.find({"restaurant_id" : "40364467"}) // Zero Cs

// Example 8 
//Change all scores of "40356483" from 10 to 11.
//$
db.business.find({"restaurant_id": "40356483"}) // has total 6 grades and 3 grades with 10 as a numeric score.
db.business.updateMany({"restaurant_id": "40356483", "grades.score" : 10}, 
                       {$set:{"grades.$.score": 11}}) 
db.business.find({"restaurant_id": "40356483"}) //One element is changed

//$[] 
db.business.drop()
//mongoimport --db msds697 --collection business --file business.json
db.business.updateMany({"restaurant_id": "40356483", "grades.score" : 10},
		   {$set:{"grades.$[].score": 11}})
db.business.find({"restaurant_id": "40356483"}) // Change all 6
		   
//$[<identifier>]
db.business.drop()
//mongoimport --db msds697 --collection business --file business.json
db.business.updateMany({"restaurant_id":"40356483"}, 
           {$set:{"grades.$[element].score":11}},
		   {arrayFilters:[{"element.score":10}]})
db.business.find({"restaurant_id": "40356483"})  // Change 3


// Example 9
// In "friends" collection,
// Delete one item which officeAddress' city is “San Francisco”
// Delete all items which officeAddress' city is “San Francisco”
// What is the best way to drop all? 
//// .deleteMany({}) vs .drop()

//Remove One
db.friends.deleteOne({"officeAddress.city":"San Francisco"})
db.friends.count()

//Remove Many
db.friend.deleteMany({"officeAddress.city":"San Francisco"})
db.friend.count()

//Drop the entire collection.
db.friend.drop()
db.friend.count()


//Extra -
// For documents in business where zipcode is 10462, and street is "Castle Hill Avenue",
// Update its grade to "A+" if score is greater than 10.
db.business.find({"address.zipcode" : "10462", "address.street" : "Castle Hill Avenue"})

db.business.update({"address.zipcode" : "10462", "address.street" : "Castle Hill Avenue"},
                   {$set:{"grades.$[elem].grade":"A+"}},
                   {arrayFilters:[{"elem.score":{$gt:10}}], multi:true})
