import{request,download}from './client';import type{RegisterVersion,CorrectionPackage,CorrectionDetail}from '../types/domain';
export const getVersions=(id:number)=>request<RegisterVersion[]>(`/batches/${id}/register/versions`);
export const downloadVersion=(id:number,v:number)=>download(`/batches/${id}/register/versions/${v}/csv`,`register-v${v}.csv`);
export const getPackages=(id:number)=>request<CorrectionPackage[]>(`/batches/${id}/corrections`);
export const getPackage=(id:number,pid:number)=>request<CorrectionDetail>(`/batches/${id}/corrections/${pid}`);
export const importCorrection=(id:number,data:{code:string;depends_on?:string;base_version?:number;csv_text:string})=>request<CorrectionDetail>(`/batches/${id}/corrections`,{method:'POST',body:JSON.stringify(data)});
export const resolvePackage=(id:number,pid:number,resolutions:{conflict_id:number;choice:string;value?:string}[])=>request<CorrectionDetail>(`/batches/${id}/corrections/${pid}/resolve`,{method:'POST',body:JSON.stringify({resolutions})});
