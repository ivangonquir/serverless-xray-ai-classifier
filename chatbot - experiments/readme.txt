The user first gives a patient id to the LLM.

We can freely have conversations with it. Every exchange will be stored in a table in DynamoDB.
If the table does not exist, it will be created automatically. This table only stores chat histories
based on the provided patient id.

**Patient Analysis should be stored in another table beforehand** -> the future model will also leverage this info.

-----------------------------------------------------

23/04/2026

pdfs are converted into raw strings, chunks of pdfs strings using the scripts in RAG folder. They are uploaded to an AWS OpenSearch main crated beforehand directly in AWS console. With the current version of the chatbot, it always retrieves 3 most relevant text chunks for the model to yield better results (the model may use it or not).

-> Regarding the workflow of the chatbot, it still needs fine tuning, since the final flow depends on the real patient data and the outcome from the VLM.