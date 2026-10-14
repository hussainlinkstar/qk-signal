export type LlmCompletionRequest = {
  audit_id: number;
  project_id?: number;
};

export type LlmCompletionResponse = {
  content: string;
};

export interface LlmProvider {
  complete(request: LlmCompletionRequest): Promise<LlmCompletionResponse>;
}
