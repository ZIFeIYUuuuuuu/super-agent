export type ChatItemKind = "user" | "thought" | "answer" | "error";

export type ChatItem = {
  id: string;
  kind: ChatItemKind;
  content: string;
  time: string;
};

export type ThreadRecord = {
  threadId: string;
  title: string;
  preview: string;
  updatedAt: string;
};

export type UploadFeedback = {
  kind: "success" | "error";
  message: string;
};
