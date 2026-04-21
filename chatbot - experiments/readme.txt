The user first gives a patient id to the LLM.

We can freely have conversations with it. Every exchange will be stored in a table in DynamoDB.
If the table does not exist, it will be created automatically. This table only stores chat histories
based on the provided patient id.

**Patient Analysis should be stored in another table beforehand** -> the future model will also leverage this info.