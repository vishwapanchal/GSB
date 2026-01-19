from fastapi import APIRouter, HTTPException, status, Query, UploadFile, File, Form, Body
from app.database import db
from app.utils.s3 import upload_file_to_s3
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from pydantic import BaseModel

router = APIRouter(prefix="/projects", tags=["Projects"])

# --- CONSTANTS ---
IST = timezone(timedelta(hours=5, minutes=30))

# --- SCHEMAS ---

class GeoPoint(BaseModel):
    lat: float
    lng: float

class Milestone(BaseModel):
    title: str
    description: Optional[str] = None
    status: str = "Pending"

class ProjectCreate(BaseModel):
    project_name: str
    description: str
    category: str
    village_name: str 
    location: str      
    start_point: GeoPoint
    end_point: GeoPoint
    contractor_name: str
    contractor_id: str
    allocated_budget: float
    approved_by: str
    start_date: datetime
    due_date: datetime
    status: str = "Proposed"
    milestones: List[str] = ["Project Initiated"] # Simplified to list of strings for easier appending

# --- ROUTES ---

# 1. CREATE PROJECT (Govt Official)
@router.post("/", status_code=status.HTTP_201_CREATED) # Changed to root / to match typical REST patterns
async def create_project(project: ProjectCreate, official_id: Optional[str] = Query(None)):
    """
    Creates a new project. 
    Frontend calls: POST /projects/?official_id=...
    """
    new_project = project.dict()
    new_project["created_at"] = datetime.now(IST)
    new_project["images"] = []
    
    # Insert into DB
    result = await db.projects.insert_one(new_project)
    
    return {
        "message": "Project created successfully",
        "project_id": str(result.inserted_id)
    }

# 2. GET PROJECTS (Unified Filter)
@router.get("/")
async def get_projects(
    village_name: Optional[str] = Query(None),
    contractor_id: Optional[str] = Query(None)
):
    """
    Unified endpoint to fetch projects.
    - If 'village_name' provided: Returns all projects for that village.
    - If 'contractor_id' provided: Returns all projects for that contractor.
    - If neither: Returns all projects.
    """
    query = {}
    if village_name:
        query["village_name"] = village_name
    if contractor_id:
        query["contractor_id"] = contractor_id

    projects = await db.projects.find(query).sort("created_at", -1).to_list(100)
    
    results = []
    for p in projects:
        p["id"] = str(p["_id"])
        del p["_id"]
        results.append(p)
        
    return results

# 3. GET PROJECT DETAILS (Full View)
@router.get("/{project_id}")
async def get_project_details(project_id: str):
    """
    Get full details including images and milestones.
    """
    try:
        oid = ObjectId(project_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid Project ID")

    project = await db.projects.find_one({"_id": oid})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project["id"] = str(project["_id"])
    del project["_id"]

    return project

# 4. UPDATE PROJECT STATUS & MILESTONES
@router.patch("/{project_id}/status")
async def update_project_status(
    project_id: str, 
    status: str = Query(...), 
    new_milestone: Optional[str] = Query(None),
    official_id: Optional[str] = Query(None)
):
    """
    Updates status and optionally adds a new milestone.
    Matches Frontend: PATCH /projects/{id}/status?status=...&new_milestone=...
    """
    try:
        oid = ObjectId(project_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid Project ID")

    update_query = {"$set": {"status": status}}

    # If a new milestone string is provided, append it to the list
    if new_milestone:
        update_query["$push"] = {"milestones": new_milestone}

    result = await db.projects.update_one(
        {"_id": oid},
        update_query
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Project not found")

    return {
        "message": "Project updated", 
        "new_status": status, 
        "milestone_added": new_milestone
    }

# 5. UPLOAD PROJECT IMAGE (Contractor)
@router.post("/{project_id}/upload-image")
async def upload_project_image(
    project_id: str,
    contractor_id: str = Query(..., description="ID of the contractor uploading"),
    file: UploadFile = File(...),
    description: str = Form("Progress Update")
):
    """
    Contractor uploads progress images.
    """
    try:
        oid = ObjectId(project_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid Project ID")

    project = await db.projects.find_one({"_id": oid})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
        
    # Verify Contractor
    if project.get("contractor_id") != contractor_id:
        raise HTTPException(status_code=403, detail="Unauthorized: You are not the assigned contractor.")

    # Upload to S3 (Mock or Real)
    image_url = await upload_file_to_s3(file, "projects") 
    # Note: Ensure your upload_file_to_s3 is async or handles file.file correctly
    
    image_record = {
        "url": image_url,
        "description": description,
        "uploaded_at": datetime.now(IST),
        "uploaded_by": contractor_id
    }

    await db.projects.update_one(
        {"_id": oid},
        {"$push": {"images": image_record}}
    )

    return {"message": "Image uploaded successfully", "url": image_url}