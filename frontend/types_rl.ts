
export interface RLTrainingStatus {
    state: 'idle' | 'training' | 'done' | 'error';
    modelLoaded: boolean;
    timestepsDone: number;
    totalTimesteps: number;
    episodeCount: number;
    meanReward: number;
    meanSharpe: number;
    totalTrades: number;
    elapsedSeconds: number;
    error?: string;
    modelPath?: string;
}
