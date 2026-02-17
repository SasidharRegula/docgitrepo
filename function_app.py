import azure.functions as func
import logging
from openai import AzureOpenAI
from azure.storage.blob import BlobServiceClient  
from azure.ai.documentintelligence import DocumentIntelligenceClient 
from azure.core.credentials import AzureKeyCredential 
import os, json, random 
from azure.cosmos import CosmosClient 
from datetime import datetime 
from concurrent.futures import ThreadPoolExecutor

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

@app.route(route="githubrepodocs")
def githubrepodocs(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')
    
    try:
        # Get environment variables with validation
        required_env_vars = {
            "BLOB_CONN_STR": os.getenv("BLOB_CONN_STR"),
            "BLOB_CONTAINER_NAME": os.getenv("BLOB_CONTAINER_NAME"),
            "DOC_INT_KEY": os.getenv("DOC_INT_KEY"),
            "DOC_INT_ENDPOINT": os.getenv("DOC_INT_ENDPOINT"),
            "AZURE_API_ENDPOINT": os.getenv("AZURE_API_ENDPOINT"),
            "AZURE_API_KEY": os.getenv("AZURE_API_KEY"),
            "AZURE_API_VERSION": os.getenv("AZURE_API_VERSION"),
            "COSMOS_CONN_STR": os.getenv("COSMOS_CONN_STR"),
            "COSMOS_DB_NAME": os.getenv("COSMOS_DB_NAME"),
            "COSMOS_CONTAINER_NAME": os.getenv("COSMOS_CONTAINER_NAME")
        }
        
        # Check for missing environment variables
        missing_vars = [key for key, value in required_env_vars.items() if not value]
        if missing_vars:
            error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
            logging.error(error_msg)
            return func.HttpResponse(error_msg, status_code=500)
        
        logging.info("All environment variables loaded successfully")
        
        # Initialize Azure clients
        logging.info("Initializing Azure clients...")
        
        blob_service = BlobServiceClient.from_connection_string(required_env_vars["BLOB_CONN_STR"]) 
        container_client = blob_service.get_container_client(required_env_vars["BLOB_CONTAINER_NAME"]) 
        
        doc_int_client = DocumentIntelligenceClient(
            endpoint=required_env_vars["DOC_INT_ENDPOINT"],
            credential=AzureKeyCredential(key=required_env_vars["DOC_INT_KEY"])
        ) 
        
        aoai_client = AzureOpenAI(
            azure_endpoint=required_env_vars["AZURE_API_ENDPOINT"],
            api_key=required_env_vars["AZURE_API_KEY"],
            api_version=required_env_vars["AZURE_API_VERSION"]
        ) 
        
        cosmos_client = CosmosClient.from_connection_string(required_env_vars["COSMOS_CONN_STR"]) 
        database = cosmos_client.get_database_client(required_env_vars["COSMOS_DB_NAME"]) 
        container = database.get_container_client(required_env_vars["COSMOS_CONTAINER_NAME"]) 
        
        logging.info("All Azure clients initialized successfully")
        
        # Get case_id from request
        case_id = req.params.get('case_id')
        if not case_id:
            try:
                req_body = req.get_json()
                case_id = req_body.get('case_id')
            except ValueError:
                pass
        
        if not case_id:
            return func.HttpResponse(
                json.dumps({"error": "case_id is required"}),
                mimetype="application/json",
                status_code=400
            )
        
        logging.info(f"Processing case_id: {case_id}")
        
        # Handle file uploads
        uploaded_files = []
        if req.files:
            uploaded_files = req.files.getlist("files")
        
        if uploaded_files:
            logging.info(f"[UPLOAD] Received {len(uploaded_files)} file(s)") 
            for file in uploaded_files: 
                filename = file.filename.replace("\\", "/")
                blob_path = f"{case_id}/{filename}"
                blob_client = container_client.get_blob_client(blob_path) 
                blob_client.upload_blob(
                    file.stream.read(),
                    overwrite=True
                ) 
                logging.info(f"[UPLOAD] Stored file -> {blob_path}") 
        
        # Scan blob storage for existing files
        attachments = []
        logging.info(f"[BLOB SCAN] Scanning container '{required_env_vars['BLOB_CONTAINER_NAME']}' for prefix '{case_id}/'") 
        
        blob_list = list(container_client.list_blobs(name_starts_with=f"{case_id}/"))
        logging.info(f"[BLOB COUNT] Found {len(blob_list)} blob(s)") 
        
        for blob in blob_list: 
            logging.info(f"Processing file: {blob.name}") 
            blob_client = container_client.get_blob_client(blob.name) 
            file_bytes = bytes(blob_client.download_blob().readall())
            attachments.append({
                "fileName": blob.name.split("/")[-1],
                "fileBytes": file_bytes
            }) 
        
        if not attachments:
            logging.warning(f"No attachments found for case {case_id}")
            return func.HttpResponse(
                json.dumps({"error": f"No attachments found in Blob for case {case_id}"}),
                mimetype="application/json",
                status_code=404
            )
        
        logging.info(f"Processing {len(attachments)} attachment(s)")
        
        # OCR processing function
        def analyze_files(file_bytes):
            try:
                poller = doc_int_client.begin_analyze_document(
                    model_id="prebuilt-layout",
                    body=file_bytes
                ) 
                result = poller.result() 
                lines = []
                for page in result.pages:
                    for line in page.lines:
                        lines.append(line.content)
                return "\n".join(lines)
            except Exception as e:
                logging.error(f"Error analyzing document: {str(e)}")
                return ""
        
        # Process all files in parallel
        logging.info("Starting OCR processing...")
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(
                analyze_files,
                [a["fileBytes"] for a in attachments]
            )) 
        
        ocr_text = "\n".join(results) 
        logging.info(f"OCR completed. Extracted {len(ocr_text)} characters")
        
        # Prepare API payload
        api_payload = {
            "caseId": case_id,
            "caseType": "Application Fraud",
            "fraudCategory": "Amount Fraud",
            "priority": "High",
            "email": {
                "from": "alerts@bankcore.com",
                "subject": "Excess Loan Amount Credited",
                "description": (
                    "System controls detected that the loan amount credited "
                    "exceeds the sanctioned amount. Preliminary review indicates "
                    "possible amount manipulation during disbursement."
                ),
                "receivedOn": "2026-02-08T10:15:00Z"
            },
            "customer": {
                "name": "Anil Sharma",
                "customerId": "CUST-774512",
                "accountType": "Retail Loan"
            },
            "attachments": [{"fileName": a["fileName"]} for a in attachments]
        } 
        
        email_description = api_payload["email"]["description"]
        
        # First GPT call - Entity extraction
        logging.info("Calling GPT for entity extraction...")
        prompt = f"""Extract ONLY the following entities. Return STRICT JSON.
                    Applicant Name
                    Customer ID
                    Branch Code
                    Requested Amount
                    Sanctioned Amount

                    EMAIL:
                    {email_description}

                    DOCUMENT TEXT:
                    {ocr_text}
                    """ 
        
        response = aoai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You extract structured fraud investigation entities."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=400
        ) 
        
        raw_output = response.choices[0].message.content 
        cleaned = raw_output.strip() 
        
        if cleaned.startswith("```"):
            cleaned = cleaned.replace("```json", "").replace("```", "").strip()
        
        try:
            cleaned_entities = json.loads(cleaned)
            logging.info(f"Entities extracted: {json.dumps(cleaned_entities)}")
        except Exception as e:
            logging.error(f"Invalid JSON from GPT: {cleaned}")
            return func.HttpResponse(
                json.dumps({"error": "Invalid JSON returned by model", "raw_output": cleaned}),
                mimetype="application/json",
                status_code=500
            )
        
        # Second GPT call - Generate summary
        logging.info("Calling GPT for summary generation...")
        final_prompt = f"""You are a senior bank fraud investigation officer.
                Using ONLY the data below, generate a clear investigation summary.
                CASE ID: {case_id} 
                EXTRACTED ENTITIES: {json.dumps(cleaned_entities, indent=2)}
                OCR DOCUMENT TEXT: {ocr_text[:2000]}
                
                Return STRICT JSON with:
                - case_id
                - summary (3-4 sentences)
                - key_findings (bullet list)
                - risk_level (LOW / MEDIUM / HIGH)
                - recommended_action (single sentence) 
                No markdown. No explanations. 
                """
        
        final_response = aoai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You produce fraud investigation summaries."},
                {"role": "user", "content": final_prompt}
            ],
            temperature=0.2,
            max_tokens=500
        ) 
        
        final_raw_output = final_response.choices[0].message.content.strip()  
        
        if final_raw_output.startswith("```"):
            final_raw_output = final_raw_output.replace("```json", "").replace("```", "").strip()
        
        summary_json = json.loads(final_raw_output)
        logging.info(f"Summary generated: {json.dumps(summary_json)}")
        
        # Store in Cosmos DB
        logging.info("Storing results in Cosmos DB...")
        doc_id = f"{case_id}-{random.randint(10, 99)}"
        document = {
            "id": doc_id,                      
            "case_id": case_id,                 
            "timestamp": datetime.utcnow().isoformat(),
            "ocr_text": ocr_text,
            "extracted_entities": cleaned_entities,
            "summary_result": summary_json
        }
        
        container.upsert_item(document) 
        logging.info(f"Document stored with id: {doc_id}")
        
        # Return success response
        return func.HttpResponse(
            json.dumps(summary_json, indent=2),
            mimetype="application/json",
            status_code=200
        )
        
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error": "Internal server error",
                "message": str(e)
            }),
            mimetype="application/json",
            status_code=500
        )
