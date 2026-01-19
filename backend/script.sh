#!/bin/bash

echo "🚀 Updating Project Routes (Added Village Filter)..."

cat <<'EOF' > app/routers/projects.py
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
    village_name: str  # <--- ADDED: To link project to a village
    location: str      # Specific site (e.g. "North Road Junction")
    start_point: GeoPoint
    end_point: GeoPoint
    contractor_name: str
    contractor_id: str
    allocated_budget: float
    approved_by: str
    start_date: datetime
    due_date: datetime
    status: str = "Proposed"
    milestones: List[Milestone] = []

class ProjectUpdateStatus(BaseModel):
    status: str

# --- ROUTES ---

# 1. CREATE PROJECT (Govt Official)
@router.post("/create", status_code=status.HTTP_201_CREATED)
async def create_project(project: ProjectCreate):
    """
    Creates a new project. 
    Requires 'village_name' to allow filtering later.
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

# 2. GET PROJECTS BY VILLAGE (New Route)
@router.get("/village/{village_name}")
async def get_projects_by_village(village_name: str):
    """
    Fetches ALL projects for a specific village.
    """
    projects = await db.projects.find({"village_name": village_name}).to_list(100)
    
    results = []
    for p in projects:
        p["id"] = str(p["_id"])
        del p["_id"]
        results.append(p)
        
    return results

# 3. GET PROJECTS FOR CONTRACTOR
@router.get("/contractor/{contractor_id}")
async def get_contractor_projects(contractor_id: str):
    """
    Returns projects assigned to a specific contractor.
    """
    projects = await db.projects.find({"contractor_id": contractor_id}).to_list(100)
    
    results = []
    for p in projects:
        p["id"] = str(p["_id"])
        del p["_id"]
        results.append(p)
        
    return results

# 4. UPLOAD PROJECT IMAGE (Contractor)
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
        
    if project.get("contractor_id") != contractor_id:
        raise HTTPException(status_code=403, detail="Unauthorized: You are not the assigned contractor.")

    image_url = upload_file_to_s3(file.file, file.filename, folder="projects")
    
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

# 5. GET PROJECT DETAILS (Full View)
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

# 6. UPDATE PROJECT STATUS
@router.patch("/{project_id}/status")
async def update_project_status(project_id: str, update: ProjectUpdateStatus):
    """
    Update status (e.g., 'In Progress', 'Completed').
    """
    try:
        oid = ObjectId(project_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid Project ID")

    result = await db.projects.update_one(
        {"_id": oid},
        {"$set": {"status": update.status}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Project not found")

    return {"message": "Project status updated", "new_status": update.status}
EOF

echo "---------------------------------------------------"
echo "✅ Added 'village_name' field & '/projects/village/{name}' route!"
echo "---------------------------------------------------"