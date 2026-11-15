from src.services import correction_service

def import_package(db,batch_id,data,user):
    return correction_service.import_correction(db,batch_id,data,user)

def resolve(db,batch_id,package_id,data,user):
    return correction_service.resolve_conflicts(db,batch_id,package_id,data,user)
