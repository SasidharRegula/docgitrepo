import azure.functions as func
import logging
from openai import AzureOpenAI
from azure.storage.blob import BlobServiceClient  
from azure.ai.documentintelligence import DocumentIntelligenceClient 
from azure.core.credentials import AzureKeyCredential 
import os,json,random 
from azure.cosmos import CosmosClient 
from datetime import datetime 
from concurrent.futures import ThreadPoolExecutor

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

@app.route(route="githubrepodocs")
def githubrepodocs(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')
    BLOB_CONN_STR=os.getenv("BLOB_CONN_STR") 
    BLOB_CONTAINER_NAME=os.getenv("BLOB_CONTAINER_NAME")
    DOC_INT_KEY=os.getenv("DOC_INT_KEY") 
    DOC_INT_ENDPOINT=os.getenv("DOC_INT_ENDPOINT")
    AZURE_API_ENDPOINT=os.getenv("AZURE_API_ENDPOINT")
    AZURE_API_KEY=os.getenv("AZURE_API_KEY")
    AZURE_API_VERSION=os.getenv("AZURE_API_VERSION") 
    COSMOS_CONN_STR=os.getenv("COSMOS_CONN_STR") 
    COSMOS_DB_NAME=os.getenv("COSMOS_DB_NAME") 
    COSMOS_CONTAINER_NAME=os.getenv("COSMOS_CONTAINER_NAME")
    name = req.params.get('name')
    if not name:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            name = req_body.get('name')

    if name:
        return func.HttpResponse(f"Hello, {name}. This HTTP triggered function executed successfully.")
    else:
        return func.HttpResponse(
             "This HTTP triggered function executed successfully. Pass a name in the query string or in the request body for a personalized response.",
             status_code=200
        )