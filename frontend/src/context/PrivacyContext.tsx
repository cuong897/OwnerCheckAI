import React, { createContext, useContext, useState } from "react";

interface PrivacyContextType {
  blurOwnerInfo: boolean;
  setBlurOwnerInfo: (value: boolean) => void;
}

const PrivacyContext = createContext<PrivacyContextType | undefined>(undefined);

export const PrivacyProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [blurOwnerInfo, setBlurOwnerInfo] = useState(true);

  return (
    <PrivacyContext.Provider value={{ blurOwnerInfo, setBlurOwnerInfo }}>
      {children}
    </PrivacyContext.Provider>
  );
};

export const usePrivacy = () => {
  const context = useContext(PrivacyContext);
  if (!context) {
    throw new Error("usePrivacy must be used within a PrivacyProvider");
  }
  return context;
};
